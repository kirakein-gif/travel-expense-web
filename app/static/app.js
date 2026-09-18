const $ = id => document.getElementById(id);
const fmt = n => n == null ? "-" : Number(n).toLocaleString("ko-KR");
let lastDistance = null, lastPayload = null, lastEvidencePayload = null, importData = null, selectedTrip = null;
let prefetchedEvidence = null, evidencePrefetchPromise = null, evidencePrefetchContext = null, evidencePrefetchSeq = 0;

const VEHICLE_SPECS = {
  gasoline:{label:"휘발유",efficiency:11.97,unit:"km/L",evidence:"gasoline"},
  diesel:{label:"경유",efficiency:12.52,unit:"km/L",evidence:"diesel"},
  lpg:{label:"LPG",efficiency:8.83,unit:"km/L",evidence:"lpg"},
  hybrid:{label:"하이브리드",efficiency:15.37,unit:"km/L",evidence:"gasoline"},
  electric:{label:"전기",efficiency:5.22,unit:"km/kWh",evidence:null},
  hydrogen:{label:"수소",efficiency:94.9,unit:"km/kg",evidence:null}
};
const PHEV_SPECS = {
  gasoline:{label:"플러그인하이브리드(휘발유)",efficiency:10.61,unit:"km/L",evidence:"gasoline"},
  electric:{label:"플러그인하이브리드(전기)",efficiency:2.84,unit:"km/kWh",evidence:null}
};

function currentVehicleSpec(){ return $("vehicle_type").value==="phev" ? PHEV_SPECS[$("phev_energy_source").value] : VEHICLE_SPECS[$("vehicle_type").value]; }
function seoulToday(){
  const parts=new Intl.DateTimeFormat("en-CA",{timeZone:"Asia/Seoul",year:"numeric",month:"2-digit",day:"2-digit"}).formatToParts(new Date());
  const map=Object.fromEntries(parts.filter(p=>p.type!=="literal").map(p=>[p.type,p.value]));
  return map.year+"-"+map.month+"-"+map.day;
}
function normSigungu(value){ return (value||"").trim().split(/\s+/)[0]; }
function days(){
  const s=new Date($("travel_date").value), e=new Date($("end_date").value);
  if(!$("travel_date").value||!$("end_date").value) return 1;
  return Math.max(1,Math.round((e-s)/86400000)+1);
}
function setTab(n){
  document.querySelectorAll(".side-step").forEach(b=>b.classList.toggle("active",b.dataset.tab===String(n)));
  document.querySelectorAll(".tab-panel").forEach(p=>p.classList.toggle("active",p.id==="tab"+n));
  if(String(n)==="2" && lastDistance && lastDistance.outside_travel_eligible) startEvidencePrefetch();
  if(window.innerWidth<1100) window.scrollTo({top:0,behavior:"smooth"});
}
document.querySelectorAll(".side-step").forEach(b=>b.addEventListener("click",()=>setTab(b.dataset.tab)));
document.querySelectorAll("[data-go]").forEach(b=>b.addEventListener("click",()=>setTab(b.dataset.go)));

function setResultState(text,kind){
  $("resultState").textContent=text;
  $("resultState").className="result-state"+(kind?" "+kind:"");
}
function setEvidencePrepStatus(text,kind){
  const el=$("evidencePrepStatus");
  if(!el)return;
  el.textContent=text||"";
  el.className="evidence-prep"+(kind?" "+kind:"")+(text?"":" hidden");
}
function invalidateEvidenceCache(){
  evidencePrefetchSeq++;
  prefetchedEvidence=null;
  evidencePrefetchPromise=null;
  evidencePrefetchContext=null;
  setEvidencePrepStatus("");
}
function blobToDataUrl(blob){
  return new Promise((resolve,reject)=>{
    const reader=new FileReader();
    reader.onload=()=>resolve(reader.result);
    reader.onerror=()=>reject(reader.error||new Error("증빙 이미지 변환 실패"));
    reader.readAsDataURL(blob);
  });
}
function evidenceContextKey(payload){
  const spec=currentVehicleSpec();
  if(!lastDistance||!spec.evidence)return null;
  return [payload.travel_date,lastDistance.province,lastDistance.sigungu,spec.evidence].join("|");
}
function evidencePayloadMatches(a,b){
  if(!a||!b)return false;
  return a.travel_date===b.travel_date &&
    a.vehicle_type===b.vehicle_type &&
    a.province===b.province &&
    a.sigungu===b.sigungu &&
    Math.abs(Number(a.expected_price)-Number(b.expected_price))<0.011;
}
function evidenceCanPrefetch(payload){
  const spec=currentVehicleSpec(),today=seoulToday();
  return Boolean(
    lastDistance && lastDistance.outside_travel_eligible &&
    spec.evidence && !payload.public_vehicle &&
    !trainingSameWorkArea(payload) &&
    payload.travel_date && payload.travel_date<today
  );
}
async function prefetchEvidenceWork(context,seq){
  const payload=basePayload(),spec=currentVehicleSpec();
  if(!evidenceCanPrefetch(payload))return null;
  setEvidencePrepStatus("오피넷 증빙 준비 중…","");
  try{
    const pp={...payload,distance_km:lastDistance.distance_km,one_way_distance_km:lastDistance.one_way_distance_km,province:lastDistance.province,sigungu:lastDistance.sigungu,origin_sigungu:lastDistance.origin_sigungu};
    const pr=await fetch("/api/price",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(pp)});
    const priceData=await pr.json();
    if(!pr.ok)throw new Error(priceData.detail||"유가 조회 실패");
    if(seq!==evidencePrefetchSeq)return null;
    if(priceData.energy_price==null||priceData.evidence_status==="manual_price"){
      setEvidencePrepStatus("");
      return null;
    }

    const evidencePayload={
      travel_date:payload.travel_date,
      vehicle_type:spec.evidence,
      province:lastDistance.province,
      sigungu:lastDistance.sigungu,
      expected_price:priceData.energy_price
    };
    const er=await fetch("/api/opinet-evidence.png",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(evidencePayload)});
    if(!er.ok){const d=await er.json();throw new Error(d.detail||"증빙 생성 실패");}
    const blob=await er.blob();
    const dataUrl=await blobToDataUrl(blob);
    if(seq!==evidencePrefetchSeq)return null;

    prefetchedEvidence={context,dataUrl,blob,evidencePayload};
    setEvidencePrepStatus("✓ 증빙 준비 완료","ready");
    return prefetchedEvidence;
  }catch(e){
    if(seq===evidencePrefetchSeq){
      prefetchedEvidence=null;
      setEvidencePrepStatus("증빙 선행 준비 실패","failed");
    }
    return null;
  }
}
function startEvidencePrefetch(){
  const payload=basePayload();
  if(!evidenceCanPrefetch(payload)){
    setEvidencePrepStatus("");
    return Promise.resolve(null);
  }
  const context=evidenceContextKey(payload);
  if(prefetchedEvidence&&prefetchedEvidence.context===context){
    setEvidencePrepStatus("✓ 증빙 준비 완료","ready");
    return Promise.resolve(prefetchedEvidence);
  }
  if(evidencePrefetchPromise&&evidencePrefetchContext===context)return evidencePrefetchPromise;

  const seq=++evidencePrefetchSeq;
  evidencePrefetchContext=context;
  evidencePrefetchPromise=prefetchEvidenceWork(context,seq).finally(()=>{
    if(seq===evidencePrefetchSeq){
      evidencePrefetchPromise=null;
      evidencePrefetchContext=null;
    }
  });
  return evidencePrefetchPromise;
}
async function evidenceForPdf(){
  if(!lastEvidencePayload)return null;
  if(evidencePrefetchPromise){
    try{await evidencePrefetchPromise;}catch(e){}
  }
  if(prefetchedEvidence&&evidencePayloadMatches(prefetchedEvidence.evidencePayload,lastEvidencePayload)){
    return prefetchedEvidence.dataUrl;
  }
  return null;
}
function downloadEvidenceBlob(blob,payload){
  const url=URL.createObjectURL(blob),a=document.createElement("a");
  a.href=url;
  a.download="오피넷증빙_"+payload.travel_date+"_"+payload.sigungu+".png";
  a.click();
  setTimeout(()=>URL.revokeObjectURL(url),1000);
}

function resetCalcFields(){
  ["final_round_trips","final_transport_distance","vehicle_spec","fuel_price_date","price","formula","amount","daily_allowance","daily_note","meal_allowance","meal_note","toll_result","parking_result","lodging_result","source","evidence","total_expense","summary_transport","summary_daily","summary_meal","summary_misc"].forEach(id=>$(id).textContent="-");
  $("fare_summary").textContent="여비 계산 전";
}
function clearPriceReview(){
  lastPayload=null; lastEvidencePayload=null;
  $("pdfButton").disabled=true; $("regulationPdfButton").disabled=true; $("evidenceButton").disabled=true; $("tab2check").textContent="";
  resetCalcFields();
  $("outputActions").classList.add("hidden");
  if(lastDistance && !lastDistance.outside_travel_eligible) setResultState("관외 대상 아님","blocked");
  else setResultState(lastDistance?"거리 확인 완료":"입력 대기",lastDistance?"partial":"");
}
function clearDistanceReview(){
  invalidateEvidenceCache();
  lastDistance=null; $("distanceNextButton").disabled=true; $("step2Button").disabled=true; $("tab1check").textContent="";
  ["resolved_origin","resolved_destination","one_way_distance","distance_source","destination_code"].forEach(id=>$(id).textContent="-");
  $("trip_summary").textContent="거리 확인 전";
  $("scopeAlert").className="scope-alert hidden"; $("scopeAlert").textContent="";
  clearPriceReview();
}
function updateVehicle(){
  const type=$("vehicle_type").value, s=currentVehicleSpec();
  $("phevEnergyWrap").classList.toggle("hidden",type!=="phev");
  $("efficiency").value=s.efficiency+" "+s.unit;
  updateManualPriceVisibility(); updatePreview();
}
function suggestedTrainingTrips(){
  const d=days(), mode=$("training_stay_mode").value;
  if(mode==="residential") return 1;
  if(mode==="nonresidential") return d;
  return Math.min(d,Math.max(1,Number($("training_round_trips").value||1)));
}
function populateSelect(id,zeroLabel,unit){
  const select=$(id), current=Number(select.value||0), max=days()*3;
  select.innerHTML="";
  for(let i=0;i<=max;i++){
    const opt=document.createElement("option"); opt.value=String(i); opt.textContent=i===0?zeroLabel:String(i)+unit; select.appendChild(opt);
  }
  select.value=String(Math.min(current,max));
}
function populateMealCounts(){
  populateSelect("provided_meals_count","0식 · 제공 없음","식");
  populateSelect("training_meal_claim_count","0회 · 청구 없음","회");
}
function updateTripType(){
  const training=$("trip_type").value==="training";
  $("normalOptions").classList.toggle("hidden",training);
  $("trainingOptions").classList.toggle("hidden",!training);
  $("roundTripWrap").classList.toggle("hidden",training);
  updateTraining(); updateManualPriceVisibility(); updatePreview();
}
function updateTraining(){
  const mode=$("training_stay_mode").value, d=days(), r=suggestedTrainingTrips();
  $("customRoundTripsWrap").classList.toggle("hidden",mode!=="custom");
  if(mode==="nonresidential") $("trainingTripHint").textContent=d+"일 교육 → 매일 출퇴근 → 왕복 "+r+"회";
  else if(mode==="residential") $("trainingTripHint").textContent=d+"일 교육 → 첫날 출발·마지막날 귀가 → 왕복 1회";
  else $("trainingTripHint").textContent=d+"일 교육 → 혼합형 → 왕복 "+r+"회";
  $("training_round_trips").max=d; updatePreview();
}
function updatePreview(){
  $("preview_days").textContent=days()+"일";
  $("preview_type").textContent=$("trip_type").value==="training"?"교육훈련":"일반출장";
}
function basePayload(){
  const type=$("vehicle_type").value, spec=currentVehicleSpec(), manual=Number($("manual_energy_price").value||0);
  return {
    travel_date:$("travel_date").value,end_date:$("end_date").value,origin:$("origin").value,destination:$("destination").value,
    purpose:$("purpose").value||null,vehicle_type:type,phev_energy_source:type==="phev"?$("phev_energy_source").value:null,
    efficiency:spec.efficiency,manual_energy_price:manual>0?manual:null,round_trip:$("round_trip").checked,
    trip_type:$("trip_type").value,public_vehicle:$("public_vehicle").checked,provided_meals_count:Number($("provided_meals_count").value||0),
    training_stay_mode:$("training_stay_mode").value,training_round_trips:$("trip_type").value==="training"&&$("training_stay_mode").value==="custom"?Number($("training_round_trips").value||1):null,
    training_meal_claim_count:Number($("training_meal_claim_count").value||0),toll_fee:Number($("toll_fee").value||0),parking_fee:Number($("parking_fee").value||0),lodging_fee:Number($("lodging_fee").value||0),
    affiliation:$("affiliation").value||null,position:$("position").value||null,traveler_name:$("traveler_name").value||null,passengers:$("passengers").value.trim()||null
  };
}
function placeText(name,address){ if(!name&&!address)return"-"; if(!name||name===address)return address||name; return name+" · "+address; }
function trainingSameWorkArea(payload){
  if(payload.trip_type!=="training"||!lastDistance) return false;
  const origin=normSigungu(lastDistance.origin_sigungu), dest=normSigungu(lastDistance.sigungu);
  return Boolean(origin)&&origin===dest;
}
function requiresOpinetPrice(payload){ return Boolean(currentVehicleSpec().evidence)&&!payload.public_vehicle&&!trainingSameWorkArea(payload); }
function updateManualPriceVisibility(){
  const payload=basePayload();
  $("manualPriceWrap").classList.toggle("hidden",!($("travel_date").value===seoulToday()&&requiresOpinetPrice(payload)));
}

function selectedParticipant(){
  if(!selectedTrip)return null;
  return selectedTrip.participants.find(p=>p.name===$("applicantSelect").value)||selectedTrip.participants[0];
}
function syncPassengerText(){
  $("passengers").value=[...document.querySelectorAll('#passengerChecks input[type="checkbox"]:checked')].map(el=>el.value).join(", ");
  clearPriceReview();
}
function renderPassengerCandidates(){
  const wrap=$("passengerCandidates"), box=$("passengerChecks"); box.innerHTML="";
  if(!selectedTrip){wrap.classList.add("hidden");return;}
  const applicant=$("applicantSelect").value, candidates=selectedTrip.participants.filter(p=>p.name!==applicant);
  if(!candidates.length){wrap.classList.add("hidden");$("passengers").value="";return;}
  wrap.classList.remove("hidden");
  candidates.forEach(p=>{
    const label=document.createElement("label"); label.className="candidate-check";
    const input=document.createElement("input"); input.type="checkbox"; input.value=p.name; input.addEventListener("change",syncPassengerText);
    const span=document.createElement("span"); span.textContent=p.name+" · "+(p.position||"직급 미확인");
    label.append(input,span); box.appendChild(label);
  });
  $("passengers").value="";
}
function applyApplicant(){
  const person=selectedParticipant(); if(!person)return;
  $("traveler_name").value=person.name||""; $("position").value=person.position||"";
  renderPassengerCandidates(); clearPriceReview();
}
function applyTrip(){
  if(!importData)return;
  selectedTrip=importData.trips[$("tripSelect").selectedIndex]||null; if(!selectedTrip)return;
  $("travel_date").value=selectedTrip.start_date; $("end_date").value=selectedTrip.end_date;
  $("origin").value=importData.affiliation||$("origin").value; $("destination").value=selectedTrip.destination||"";
  $("purpose").value=selectedTrip.purpose||""; $("affiliation").value=importData.affiliation||"";
  populateMealCounts();
  $("applicantSelect").innerHTML="";
  selectedTrip.participants.forEach(p=>{const opt=document.createElement("option");opt.value=p.name;opt.textContent=p.name+" · "+(p.position||"직급 미확인");$("applicantSelect").appendChild(opt);});
  if(selectedTrip.default_applicant)$("applicantSelect").value=selectedTrip.default_applicant;
  applyApplicant(); clearDistanceReview(); updateTripType(); updateManualPriceVisibility(); setTab(1);
  $("globalStatus").textContent="출장정보를 자동입력했습니다. 내용을 확인·수정한 뒤 거리를 확인해주세요.";
}
function renderImport(data){
  importData=data; $("importChooser").classList.remove("hidden"); $("tripSelect").innerHTML="";
  data.trips.forEach(t=>{const opt=document.createElement("option");opt.value=t.id;opt.textContent=t.label;$("tripSelect").appendChild(opt);});
  $("fileStatus").textContent=data.document_type_label+" · "+data.page_count+"페이지 · 출장 "+data.trip_count+"건 인식";
  applyTrip();
}
async function uploadTravelPdf(file){
  if(!file)return;
  if(!file.name.toLowerCase().endsWith(".pdf")){$("fileStatus").textContent="PDF 파일만 올릴 수 있습니다.";return;}
  const form=new FormData();form.append("file",file);$("fileStatus").textContent="출장신청서 분석 중...";$("globalStatus").textContent="PDF에서 출장정보를 읽는 중...";
  try{
    const r=await fetch("/api/import-travel-pdf",{method:"POST",body:form}),data=await r.json();
    if(!r.ok)throw new Error(data.detail||"PDF 분석 실패"); renderImport(data);
  }catch(e){$("fileStatus").textContent=e.message;$("globalStatus").textContent=e.message;}
}
$("pdfFile").addEventListener("change",e=>uploadTravelPdf(e.target.files[0]));
$("tripSelect").addEventListener("change",applyTrip); $("applicantSelect").addEventListener("change",applyApplicant);
const dz=$("dropZone");
["dragenter","dragover"].forEach(ev=>dz.addEventListener(ev,e=>{e.preventDefault();dz.classList.add("dragging");}));
["dragleave","drop"].forEach(ev=>dz.addEventListener(ev,e=>{e.preventDefault();dz.classList.remove("dragging");}));
dz.addEventListener("drop",e=>uploadTravelPdf(e.dataTransfer.files[0]));

[$("vehicle_type"),$("phev_energy_source")].forEach(el=>el.addEventListener("change",()=>{invalidateEvidenceCache();clearPriceReview();updateVehicle();}));
[$("trip_type"),$("round_trip")].forEach(el=>el.addEventListener("change",()=>{clearPriceReview();updateTripType();}));
[$("travel_date"),$("end_date")].forEach(el=>el.addEventListener("change",()=>{invalidateEvidenceCache();clearPriceReview();populateMealCounts();updateTripType();updateManualPriceVisibility();}));
[$("training_stay_mode"),$("training_round_trips")].forEach(el=>el.addEventListener("change",()=>{clearPriceReview();updateTraining();updateManualPriceVisibility();}));
["training_meal_claim_count","provided_meals_count","public_vehicle","toll_fee","parking_fee","lodging_fee","manual_energy_price"].forEach(id=>$(id).addEventListener("change",()=>{clearPriceReview();updateManualPriceVisibility();}));
["origin","destination"].forEach(id=>$(id).addEventListener("input",clearDistanceReview));

const today=seoulToday(); $("travel_date").value=today; $("end_date").value=today;
populateMealCounts(); updateVehicle(); updateTripType(); updateManualPriceVisibility(); updatePreview();
$("distanceNextButton").addEventListener("click",()=>{if(lastDistance&&lastDistance.outside_travel_eligible)setTab(2);});

$("distanceButton").addEventListener("click",async()=>{
  if(!$("travel_date").value||!$("end_date").value||$("origin").value.trim().length<2||$("destination").value.trim().length<2){$("globalStatus").textContent="출장일과 출발지·출장지를 확인해주세요.";return;}
  $("distanceButton").disabled=true;$("distanceNextButton").disabled=true;$("globalStatus").textContent="기관명·주소 확인 및 거리 계산 중...";
  try{
    const payload=basePayload(),r=await fetch("/api/distance",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)}),data=await r.json();
    if(!r.ok)throw new Error(data.detail||"거리 계산 실패"); lastDistance=data;
    $("resolved_origin").textContent=placeText(data.resolved_origin_name,data.resolved_origin_address);
    $("resolved_destination").textContent=placeText(data.resolved_destination_name,data.resolved_destination_address);
    $("one_way_distance").textContent=fmt(data.one_way_distance_km)+" km";$("distance_source").textContent=data.distance_source+(data.distance_cache_hit?" · 캐시":"");
    $("destination_code").textContent=data.destination_support_office||data.destination_code||data.sigungu||"-";
    const originLabel=data.resolved_origin_name||payload.origin;
    const destinationLabel=data.resolved_destination_name||payload.destination;
    $("trip_summary").textContent=originLabel+" → "+destinationLabel+" · 편도 "+fmt(data.one_way_distance_km)+"km";
    $("scopeAlert").className="scope-alert "+(data.outside_travel_eligible?"eligible":"blocked");
    $("scopeAlert").textContent=(data.outside_travel_eligible?"관외여비 지급 대상 · ":"관외여비 지급 대상 아님 · ")+data.outside_travel_reason;
    updateManualPriceVisibility();

    if(data.outside_travel_eligible){
      $("tab1check").textContent="✓"; $("distanceNextButton").disabled=false; $("step2Button").disabled=false;
      setResultState("관외 대상 · 거리 확인 완료","partial");
      $("globalStatus").textContent="관외여비 지급 대상입니다. 오른쪽 판정과 거리를 확인한 뒤 여비 상세로 이동하세요.";
    }else{
      $("tab1check").textContent="!"; $("distanceNextButton").disabled=true; $("step2Button").disabled=true;
      setResultState("관외 대상 아님","blocked");
      $("globalStatus").textContent="관외여비 지급 대상이 아닙니다. "+data.outside_travel_reason;
    }
  }catch(e){$("globalStatus").textContent=e.message;}finally{$("distanceButton").disabled=false;}
});

$("calculateButton").addEventListener("click",async()=>{
  if(!lastDistance){$("globalStatus").textContent="먼저 1단계에서 거리를 확인해주세요.";setTab(1);return;}
  if(!lastDistance.outside_travel_eligible){$("globalStatus").textContent="관외여비 지급 대상이 아닙니다. "+lastDistance.outside_travel_reason;setTab(1);return;}
  const payload=basePayload(),today=seoulToday();
  if(requiresOpinetPrice(payload)&&payload.travel_date>today){$("globalStatus").textContent="미래 날짜의 오피넷 유가는 조회할 수 없습니다.";return;}
  if(requiresOpinetPrice(payload)&&payload.travel_date===today&&!payload.manual_energy_price){$("globalStatus").textContent="당일 오피넷 일평균 유가는 아직 제공되지 않습니다. 적용 유가를 직접 입력해주세요.";$("manual_energy_price").focus();return;}
  $("calculateButton").disabled=true;$("globalStatus").textContent="운임·일비·식비 계산 중...";
  try{
    const pp={...payload,distance_km:lastDistance.distance_km,one_way_distance_km:lastDistance.one_way_distance_km,province:lastDistance.province,sigungu:lastDistance.sigungu,origin_sigungu:lastDistance.origin_sigungu};
    const r=await fetch("/api/price",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(pp)}),data=await r.json();if(!r.ok)throw new Error(data.detail||"여비 계산 실패");lastPayload=payload;
    $("final_round_trips").textContent=data.round_trip_count===0.5?"편도":fmt(data.round_trip_count)+"회";$("final_transport_distance").textContent=fmt(data.transport_distance_km)+" km";
    $("vehicle_spec").textContent=(data.vehicle_label||currentVehicleSpec().label)+" · "+(data.effective_efficiency||currentVehicleSpec().efficiency)+" "+(data.efficiency_unit||currentVehicleSpec().unit);
    $("fuel_price_date").textContent=data.fuel_price_date?data.fuel_price_date+" · "+(data.evidence_status==="manual_price"?"수동입력":"출장 첫째 날"):"해당 없음";
    $("price").textContent=data.energy_price==null?"해당 없음 / 연결 예정":fmt(data.energy_price)+" 원";$("formula").textContent=data.calculation_formula||"-";
    $("amount").textContent=data.estimated_transport_cost==null?"단가 연결 후 계산":fmt(data.estimated_transport_cost)+" 원";
    $("daily_allowance").textContent=fmt(data.daily_allowance)+" 원";$("daily_note").textContent=data.daily_note||"-";$("meal_allowance").textContent=fmt(data.meal_allowance)+" 원";$("meal_note").textContent=data.meal_note||"-";
    $("toll_result").textContent=fmt(data.toll_fee)+" 원";$("parking_result").textContent=fmt(data.parking_fee)+" 원";$("lodging_result").textContent=fmt(data.lodging_fee)+" 원";
    $("total_expense").textContent=data.total_expense==null?"자동차 단가 연결 후 확정":fmt(data.total_expense)+" 원";
    $("summary_transport").textContent=data.estimated_transport_cost==null?"-":fmt(data.estimated_transport_cost)+" 원";
    $("summary_daily").textContent=fmt(data.daily_allowance)+" 원";
    $("summary_meal").textContent=fmt(data.meal_allowance)+" 원";
    $("summary_misc").textContent=fmt(Number(data.toll_fee||0)+Number(data.parking_fee||0)+Number(data.lodging_fee||0))+" 원";
    $("fare_summary").textContent=days()+"일 · "+($("trip_type").value==="training"?"교육훈련":"일반출장")+" · 자동차운임 "+(data.estimated_transport_cost==null?"-":fmt(data.estimated_transport_cost)+"원")+" · 일비 "+fmt(data.daily_allowance)+"원 · 식비 "+fmt(data.meal_allowance)+"원";
    $("source").textContent=(data.price_source||"-")+(data.price_cache_hit?" · 캐시":"");
    const spec=currentVehicleSpec(),canEvidence=spec.evidence&&data.energy_price!=null&&!payload.public_vehicle&&data.evidence_status!=="manual_price";
    if(canEvidence){lastEvidencePayload={travel_date:payload.travel_date,vehicle_type:spec.evidence,province:lastDistance.province,sigungu:lastDistance.sigungu,expected_price:data.energy_price};$("evidenceButton").disabled=false;$("evidence").textContent="API 가격 확인 · 증빙 생성 대기";}
    else{lastEvidencePayload=null;$("evidenceButton").disabled=true;$("evidence").textContent=data.evidence_status;}
    $("pdfButton").disabled=false;$("regulationPdfButton").disabled=false;$("outputActions").classList.remove("hidden");$("tab2check").textContent="✓";setResultState("최종 산출 완료","done");
    $("globalStatus").textContent="여비 계산 완료 · 오른쪽 최종 산출을 확인하고 위쪽에서 증빙 또는 PDF를 생성하세요.";
  }catch(e){$("globalStatus").textContent=e.message;}finally{$("calculateButton").disabled=false;}
});

$("evidenceButton").addEventListener("click",async()=>{
  if(!lastEvidencePayload)return;
  $("evidenceButton").disabled=true;
  const old=$("evidenceButton").textContent;
  $("evidenceButton").textContent="증빙 준비 중...";
  try{
    if(evidencePrefetchPromise){
      $("globalStatus").textContent="미리 준비 중인 오피넷 증빙을 기다리는 중...";
      try{await evidencePrefetchPromise;}catch(e){}
    }
    if(prefetchedEvidence&&evidencePayloadMatches(prefetchedEvidence.evidencePayload,lastEvidencePayload)){
      downloadEvidenceBlob(prefetchedEvidence.blob,lastEvidencePayload);
      $("evidence").textContent="verified_web_capture · 임시 캐시";
      $("globalStatus").textContent="미리 준비한 오피넷 증빙을 바로 내려받았습니다.";
      return;
    }

    $("globalStatus").textContent="오피넷 증빙 화면 생성 중...";
    const response=await fetch("/api/opinet-evidence.png",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(lastEvidencePayload)});
    if(!response.ok){const d=await response.json();throw new Error(d.detail||"증빙 생성 실패");}
    const blob=await response.blob(),dataUrl=await blobToDataUrl(blob);
    prefetchedEvidence={
      context:evidenceContextKey(basePayload()),
      dataUrl,
      blob,
      evidencePayload:lastEvidencePayload
    };
    setEvidencePrepStatus("✓ 증빙 준비 완료","ready");
    downloadEvidenceBlob(blob,lastEvidencePayload);
    $("evidence").textContent="verified_web_capture · 임시 캐시";
    $("globalStatus").textContent="증빙 생성 완료 · 같은 출장의 PDF에서는 재사용합니다.";
  }catch(e){
    $("evidence").textContent="evidence_failed";
    $("globalStatus").textContent="증빙 생성 실패 · "+e.message;
  }finally{
    $("evidenceButton").textContent=old;
    $("evidenceButton").disabled=false;
  }
});
$("pdfButton").addEventListener("click",async()=>{
  if(!lastPayload)return;
  $("pdfButton").disabled=true;
  const old=$("pdfButton").textContent;
  $("pdfButton").textContent="PDF 생성 중...";
  try{
    const current=basePayload();
    const cachedEvidence=await evidenceForPdf();
    const pdfPayload={...lastPayload,affiliation:current.affiliation,position:current.position,traveler_name:current.traveler_name,passengers:current.passengers,purpose:current.purpose,manual_energy_price:current.manual_energy_price,evidence_image_base64:cachedEvidence};
    $("globalStatus").textContent=cachedEvidence?"준비된 오피넷 증빙을 재사용하여 PDF 생성 중...":"PDF 생성 중...";
    const response=await fetch("/api/report.pdf",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(pdfPayload)});
    if(!response.ok){const d=await response.json();throw new Error(d.detail||"PDF 생성 실패");}
    const blob=await response.blob(),url=URL.createObjectURL(blob),a=document.createElement("a");
    a.href=url;a.download="여비산출내역_"+pdfPayload.travel_date+".pdf";a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
    $("globalStatus").textContent=cachedEvidence?"PDF 생성 완료 · 오피넷 증빙 재사용":"PDF 생성 완료";
  }catch(e){
    $("globalStatus").textContent=e.message;
  }finally{
    $("pdfButton").textContent=old;
    $("pdfButton").disabled=false;
  }
});
$("regulationPdfButton").addEventListener("click",async()=>{
  if(!lastPayload)return;
  $("regulationPdfButton").disabled=true;
  const old=$("regulationPdfButton").textContent;
  $("regulationPdfButton").textContent="규정서식 생성 중...";
  try{
    const current=basePayload();
    const cachedEvidence=await evidenceForPdf();
    const pdfPayload={...lastPayload,affiliation:current.affiliation,position:current.position,traveler_name:current.traveler_name,passengers:current.passengers,purpose:current.purpose,manual_energy_price:current.manual_energy_price,evidence_image_base64:cachedEvidence};
    $("globalStatus").textContent=cachedEvidence?"준비된 오피넷 증빙을 재사용하여 규정서식 생성 중...":"규정서식 PDF 생성 중...";
    const response=await fetch("/api/report-regulation.pdf",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(pdfPayload)});
    if(!response.ok){const d=await response.json();throw new Error(d.detail||"규정서식 PDF 생성 실패");}
    const blob=await response.blob(),url=URL.createObjectURL(blob),a=document.createElement("a");
    a.href=url;
    a.download="규정서식_여비신청서_"+pdfPayload.travel_date+".pdf";
    a.click();
    setTimeout(()=>URL.revokeObjectURL(url),1000);
    $("globalStatus").textContent=cachedEvidence?"규정서식 생성 완료 · 오피넷 증빙 재사용":"규정서식 PDF 생성 완료";
  }catch(e){
    $("globalStatus").textContent=e.message;
  }finally{
    $("regulationPdfButton").textContent=old;
    $("regulationPdfButton").disabled=false;
  }
});
