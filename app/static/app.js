const $ = id => document.getElementById(id);
const fmt = n => n == null ? "-" : Number(n).toLocaleString("ko-KR");
let lastDistance = null;
let lastPayload = null;
let lastEvidencePayload = null;

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

function currentVehicleSpec(){
  if($("vehicle_type").value==="phev") return PHEV_SPECS[$("phev_energy_source").value];
  return VEHICLE_SPECS[$("vehicle_type").value];
}
function seoulToday(){
  const parts=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Seoul',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date());
  const map=Object.fromEntries(parts.filter(p=>p.type!=="literal").map(p=>[p.type,p.value]));
  return `${map.year}-${map.month}-${map.day}`;
}
function normSigungu(value){return (value||'').trim().split(/\s+/)[0];}
function days(){
  const s=new Date($("travel_date").value), e=new Date($("end_date").value);
  if(!$("travel_date").value||!$("end_date").value) return 1;
  return Math.max(1,Math.round((e-s)/86400000)+1);
}
function setTab(n){
  document.querySelectorAll('.tab').forEach(b=>b.classList.toggle('active',b.dataset.tab===String(n)));
  document.querySelectorAll('.tab-panel').forEach(p=>p.classList.toggle('active',p.id===`tab${n}`));
  window.scrollTo({top:0,behavior:'smooth'});
}
document.querySelectorAll('.tab').forEach(b=>b.addEventListener('click',()=>setTab(b.dataset.tab)));
document.querySelectorAll('[data-go]').forEach(b=>b.addEventListener('click',()=>setTab(b.dataset.go)));

function clearPriceReview(){
  lastPayload=null; lastEvidencePayload=null;
  $("resultNextButton").disabled=true; $("pdfButton").disabled=true; $("evidenceButton").disabled=true;
  $("tab2check").textContent='';
  ["review_formula","review_transport","review_daily","review_meal","review_total"].forEach(id=>{if($(id)) $(id).textContent='-';});
}
function clearDistanceReview(){
  lastDistance=null; $("distanceNextButton").disabled=true; $("tab1check").textContent=''; clearPriceReview();
}
function updateVehicle(){
  const type=$("vehicle_type").value;
  $("phevEnergyWrap").classList.toggle('hidden',type!=="phev");
  const s=currentVehicleSpec();
  $("efficiency").value=`${s.efficiency} ${s.unit}`;
  updateManualPriceVisibility(); updatePreview();
}
function suggestedTrainingTrips(){
  const d=days(), mode=$("training_stay_mode").value;
  if(mode==="residential") return 1;
  if(mode==="nonresidential") return d;
  return Math.min(d,Math.max(1,Number($("training_round_trips").value||1)));
}
function populateTrainingMealCounts(){
  const select=$("training_meal_claim_count"), current=Number(select.value||0), max=days()*3;
  select.innerHTML='';
  for(let i=0;i<=max;i++){const opt=document.createElement('option'); opt.value=String(i); opt.textContent=i===0?'0회 · 청구 없음':`${i}회`; select.appendChild(opt);}
  select.value=String(Math.min(current,max));
}
function updateTripType(){
  const training=$("trip_type").value==="training";
  $("normalOptions").classList.toggle('hidden',training);
  $("trainingOptions").classList.toggle('hidden',!training);
  $("roundTripWrap").classList.toggle('hidden',training);
  updateTraining(); updateManualPriceVisibility(); updatePreview();
}
function updateTraining(){
  const mode=$("training_stay_mode").value;
  $("customRoundTripsWrap").classList.toggle('hidden',mode!=="custom");
  const d=days(), r=suggestedTrainingTrips();
  if(mode==="nonresidential") $("trainingTripHint").textContent=`${d}일 교육 → 매일 출퇴근 → 왕복 ${r}회`;
  else if(mode==="residential") $("trainingTripHint").textContent=`${d}일 교육 → 첫날 출발·마지막날 귀가 → 왕복 1회`;
  else $("trainingTripHint").textContent=`${d}일 교육 → 혼합형 → 왕복 ${r}회`;
  $("training_round_trips").max=d; updatePreview();
}
function updatePreview(){
  const training=$("trip_type").value==="training", s=currentVehicleSpec(), d=days();
  $("preview_days").textContent=`${d}일`;
  $("preview_type").textContent=training?"교육훈련":"일반출장";
  $("preview_round_trips").textContent=training?`${suggestedTrainingTrips()}회`:($("round_trip").checked?"1회":"편도");
  $("preview_vehicle").textContent=`${s.label} · ${s.efficiency} ${s.unit}`;
  const date=$("travel_date").value;
  $("preview_fuel_date").textContent=date===seoulToday()?`${date} · 당일 수동입력`:date?`${date} · 첫째 날`:'첫째 날';
}
function basePayload(){
  const type=$("vehicle_type").value, spec=currentVehicleSpec();
  const manual=Number($("manual_energy_price").value||0);
  return {
    travel_date:$("travel_date").value,end_date:$("end_date").value,origin:$("origin").value,destination:$("destination").value,
    purpose:$("purpose").value||null,vehicle_type:type,phev_energy_source:type==="phev"?$("phev_energy_source").value:null,
    efficiency:spec.efficiency,manual_energy_price:manual>0?manual:null,round_trip:$("round_trip").checked,
    trip_type:$("trip_type").value,public_vehicle:$("public_vehicle").checked,provided_meals_count:Number($("provided_meals_count").value||0),
    training_stay_mode:$("training_stay_mode").value,training_round_trips:$("trip_type").value==="training"&&$("training_stay_mode").value==="custom"?Number($("training_round_trips").value||1):null,
    training_meal_claim_count:Number($("training_meal_claim_count").value||0),toll_fee:Number($("toll_fee").value||0),parking_fee:Number($("parking_fee").value||0),lodging_fee:Number($("lodging_fee").value||0),
    affiliation:$("affiliation").value||null,position:$("position").value||null,traveler_name:$("traveler_name").value||null
  };
}
function placeText(name,address){if(!name&&!address)return"-"; if(!name||name===address)return address||name; return `${name} · ${address}`;}
function trainingSameWorkArea(payload){
  if(payload.trip_type!=="training"||!lastDistance) return false;
  const origin=normSigungu(lastDistance.origin_sigungu), dest=normSigungu(lastDistance.sigungu);
  return Boolean(origin)&&origin===dest;
}
function requiresOpinetPrice(payload){return Boolean(currentVehicleSpec().evidence)&&!payload.public_vehicle&&!trainingSameWorkArea(payload);}
function updateManualPriceVisibility(){
  const payload=basePayload();
  const show=Boolean($("travel_date").value===seoulToday() && requiresOpinetPrice(payload));
  $("manualPriceWrap").classList.toggle('hidden',!show);
}

[$("vehicle_type"),$("phev_energy_source")].forEach(el=>el.addEventListener('change',()=>{clearPriceReview();updateVehicle();}));
[$("trip_type"),$("round_trip")].forEach(el=>el.addEventListener('change',()=>{clearPriceReview();updateTripType();}));
[$("travel_date"),$("end_date")].forEach(el=>el.addEventListener('change',()=>{clearPriceReview();populateTrainingMealCounts();updateTripType();updateManualPriceVisibility();}));
[$("training_stay_mode"),$("training_round_trips")].forEach(el=>el.addEventListener('change',()=>{clearPriceReview();updateTraining();updateManualPriceVisibility();}));
$("training_meal_claim_count").addEventListener('change',clearPriceReview);
["provided_meals_count","public_vehicle","toll_fee","parking_fee","lodging_fee","manual_energy_price"].forEach(id=>$(id).addEventListener('change',()=>{clearPriceReview();updateManualPriceVisibility();}));
["origin","destination"].forEach(id=>$(id).addEventListener('input',clearDistanceReview));

const today=seoulToday();
$("travel_date").value=today; $("end_date").value=today;
populateTrainingMealCounts(); updateVehicle(); updateTripType(); updateManualPriceVisibility();

$("distanceNextButton").addEventListener('click',()=>{if(lastDistance) setTab(2);});
$("resultNextButton").addEventListener('click',()=>{if(lastPayload) setTab(3);});

$("distanceButton").addEventListener('click',async()=>{
  if(!$("travel_date").value||!$("end_date").value||$("origin").value.trim().length<2||$("destination").value.trim().length<2){$("globalStatus").textContent="출장일과 출발지·출장지를 확인해주세요.";return;}
  $("distanceButton").disabled=true; $("distanceNextButton").disabled=true; $("globalStatus").textContent="기관명·주소 확인 및 거리 계산 중...";
  try{
    const payload=basePayload();
    const r=await fetch('/api/distance',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)}); const data=await r.json();
    if(!r.ok) throw new Error(data.detail||'거리 계산 실패');
    lastDistance=data;
    $("resolved_origin").textContent=placeText(data.resolved_origin_name,data.resolved_origin_address); $("resolved_destination").textContent=placeText(data.resolved_destination_name,data.resolved_destination_address);
    $("one_way_distance").textContent=`${fmt(data.one_way_distance_km)} km`; $("distance_source").textContent=data.distance_source+(data.distance_cache_hit?' · 캐시':''); $("destination_code").textContent=data.destination_support_office||data.destination_code||data.sigungu||'-';
    $("tab1check").textContent='✓'; $("distanceNextButton").disabled=false; updateManualPriceVisibility();
    $("globalStatus").textContent="거리 확인 완료 · 오른쪽 결과를 확인한 뒤 다음 단계로 이동하세요.";
  }catch(e){$("globalStatus").textContent=e.message;} finally{$("distanceButton").disabled=false;}
});

$("calculateButton").addEventListener('click',async()=>{
  if(!lastDistance){$("globalStatus").textContent="먼저 1단계에서 거리를 확인해주세요.";setTab(1);return;}
  const payload=basePayload(), today=seoulToday();
  if(requiresOpinetPrice(payload)&&payload.travel_date>today){$("globalStatus").textContent="미래 날짜의 오피넷 유가는 조회할 수 없습니다.";return;}
  if(requiresOpinetPrice(payload)&&payload.travel_date===today&&!payload.manual_energy_price){$("globalStatus").textContent="당일 오피넷 일평균 유가는 아직 제공되지 않습니다. 적용 유가를 직접 입력해주세요.";$("manual_energy_price").focus();return;}

  $("calculateButton").disabled=true; $("resultNextButton").disabled=true; $("globalStatus").textContent="운임·일비·식비 계산 중...";
  try{
    const pp={...payload,distance_km:lastDistance.distance_km,one_way_distance_km:lastDistance.one_way_distance_km,province:lastDistance.province,sigungu:lastDistance.sigungu,origin_sigungu:lastDistance.origin_sigungu};
    const r=await fetch('/api/price',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(pp)}); const data=await r.json();
    if(!r.ok) throw new Error(data.detail||'여비 계산 실패');
    lastPayload=payload;
    $("final_origin").textContent=placeText(lastDistance.resolved_origin_name,lastDistance.resolved_origin_address); $("final_destination").textContent=placeText(lastDistance.resolved_destination_name,lastDistance.resolved_destination_address);
    $("final_one_way").textContent=`${fmt(lastDistance.one_way_distance_km)} km`; $("final_round_trips").textContent=data.round_trip_count===0.5?'편도':`${fmt(data.round_trip_count)}회`; $("final_transport_distance").textContent=`${fmt(data.transport_distance_km)} km`;
    $("vehicle_spec").textContent=`${data.vehicle_label||currentVehicleSpec().label} · ${data.effective_efficiency||currentVehicleSpec().efficiency} ${data.efficiency_unit||currentVehicleSpec().unit}`;
    $("fuel_price_date").textContent=data.fuel_price_date?`${data.fuel_price_date} · ${data.evidence_status==='manual_price'?'수동입력':'출장 첫째 날'}`:'해당 없음';
    $("price").textContent=data.energy_price==null?'해당 없음 / 연결 예정':`${fmt(data.energy_price)} 원`; $("formula").textContent=data.calculation_formula||'-'; $("amount").textContent=data.estimated_transport_cost==null?'단가 연결 후 계산':`${fmt(data.estimated_transport_cost)} 원`;
    $("daily_allowance").textContent=`${fmt(data.daily_allowance)} 원`; $("daily_note").textContent=data.daily_note||'-'; $("meal_allowance").textContent=`${fmt(data.meal_allowance)} 원`; $("meal_note").textContent=data.meal_note||'-';
    $("toll_result").textContent=`${fmt(data.toll_fee)} 원`; $("parking_result").textContent=`${fmt(data.parking_fee)} 원`; $("lodging_result").textContent=`${fmt(data.lodging_fee)} 원`; $("total_expense").textContent=data.total_expense==null?'자동차 단가 연결 후 확정':`${fmt(data.total_expense)} 원`; $("source").textContent=(data.price_source||'-')+(data.price_cache_hit?' · 캐시':'');
    $("review_formula").textContent=data.calculation_formula||'-'; $("review_transport").textContent=data.estimated_transport_cost==null?'단가 연결 후 계산':`${fmt(data.estimated_transport_cost)} 원`; $("review_daily").textContent=`${fmt(data.daily_allowance)} 원`; $("review_meal").textContent=`${fmt(data.meal_allowance)} 원`; $("review_total").textContent=data.total_expense==null?'단가 연결 후 확정':`${fmt(data.total_expense)} 원`;

    const spec=currentVehicleSpec();
    const canEvidence=spec.evidence&&data.energy_price!=null&&!payload.public_vehicle&&data.evidence_status!=="manual_price";
    if(canEvidence){lastEvidencePayload={travel_date:payload.travel_date,vehicle_type:spec.evidence,province:lastDistance.province,sigungu:lastDistance.sigungu,expected_price:data.energy_price};$("evidenceButton").disabled=false;$("evidence").textContent='API 가격 확인 · 증빙 생성 대기';}
    else{lastEvidencePayload=null;$("evidenceButton").disabled=true;$("evidence").textContent=data.evidence_status;}
    $("pdfButton").disabled=false; $("resultNextButton").disabled=false; $("tab2check").textContent='✓'; $("globalStatus").textContent="여비 계산 완료 · 오른쪽 계산값을 확인한 뒤 결과·증빙 단계로 이동하세요.";
  }catch(e){$("globalStatus").textContent=e.message;} finally{$("calculateButton").disabled=false;}
});

$("evidenceButton").addEventListener('click',async()=>{
  if(!lastEvidencePayload)return; $("evidenceButton").disabled=true; const old=$("evidenceButton").textContent; $("evidenceButton").textContent='증빙 생성 중...'; $("globalStatus").textContent='오피넷 증빙 화면 생성 중...';
  try{const r=await fetch('/api/opinet-evidence.png',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(lastEvidencePayload)}); if(!r.ok){const d=await r.json();throw new Error(d.detail||'증빙 생성 실패');} const blob=await r.blob(),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=`오피넷증빙_${lastEvidencePayload.travel_date}_${lastEvidencePayload.sigungu}.png`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);$("evidence").textContent='verified_web_capture';$("globalStatus").textContent='증빙 생성 완료';}
  catch(e){$("evidence").textContent='evidence_failed';$("globalStatus").textContent=`증빙 생성 실패 · ${e.message}`;} finally{$("evidenceButton").textContent=old;$("evidenceButton").disabled=false;}
});

$("pdfButton").addEventListener('click',async()=>{
  if(!lastPayload)return; $("pdfButton").disabled=true; const old=$("pdfButton").textContent; $("pdfButton").textContent='PDF 생성 중...';
  try{const current=basePayload(); const pdfPayload={...lastPayload,affiliation:current.affiliation,position:current.position,traveler_name:current.traveler_name,purpose:current.purpose,manual_energy_price:current.manual_energy_price}; const r=await fetch('/api/report.pdf',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(pdfPayload)}); if(!r.ok){const d=await r.json();throw new Error(d.detail||'PDF 생성 실패');} const blob=await r.blob(),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=`여비산출내역_${pdfPayload.travel_date}.pdf`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
  catch(e){$("globalStatus").textContent=e.message;} finally{$("pdfButton").textContent=old;$("pdfButton").disabled=false;}
});