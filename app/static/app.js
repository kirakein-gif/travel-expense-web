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

function updateVehicle(){
  const type=$("vehicle_type").value;
  $("phevEnergyWrap").classList.toggle('hidden',type!=="phev");
  const s=currentVehicleSpec();
  $("efficiency").value=`${s.efficiency} ${s.unit}`;
  updatePreview();
}

function suggestedTrainingTrips(){
  const d=days(), mode=$("training_stay_mode").value;
  if(mode==="residential") return 1;
  if(mode==="nonresidential") return d;
  return Math.min(d,Math.max(1,Number($("training_round_trips").value||1)));
}

function populateTrainingMealCounts(){
  const select=$("training_meal_claim_count");
  const current=Number(select.value||0);
  const max=days()*3;
  select.innerHTML='';
  for(let i=0;i<=max;i++){
    const opt=document.createElement('option');
    opt.value=String(i);
    opt.textContent=i===0?'0회 · 청구 없음':`${i}회`;
    select.appendChild(opt);
  }
  select.value=String(Math.min(current,max));
}

function updateTripType(){
  const training=$("trip_type").value==="training";
  $("normalOptions").classList.toggle('hidden',training);
  $("trainingOptions").classList.toggle('hidden',!training);
  $("roundTripWrap").classList.toggle('hidden',training);
  updateTraining();
  updatePreview();
}

function updateTraining(){
  const mode=$("training_stay_mode").value;
  $("customRoundTripsWrap").classList.toggle('hidden',mode!=="custom");
  const d=days(), r=suggestedTrainingTrips();
  if(mode==="nonresidential") $("trainingTripHint").textContent=`${d}일 교육 → 매일 출퇴근 → 왕복 ${r}회`;
  else if(mode==="residential") $("trainingTripHint").textContent=`${d}일 교육 → 첫날 출발·마지막날 귀가 → 왕복 1회`;
  else $("trainingTripHint").textContent=`${d}일 교육 → 혼합형 → 왕복 ${r}회`;
  $("training_round_trips").max=d;
  updatePreview();
}

function updatePreview(){
  const training=$("trip_type").value==="training", s=currentVehicleSpec(), d=days();
  $("preview_days").textContent=`${d}일`;
  $("preview_type").textContent=training?"교육훈련":"일반출장";
  $("preview_round_trips").textContent=training?`${suggestedTrainingTrips()}회`:($("round_trip").checked?"1회":"편도");
  $("preview_vehicle").textContent=`${s.label} · ${s.efficiency} ${s.unit}`;
  $("preview_fuel_date").textContent=$("travel_date").value?`${$("travel_date").value} · 첫째 날`:'첫째 날';
  $("preview_daily").textContent=training?"등록·수료일 전액 / 중간일 숙박 여부 반영":"25,000원 × 일수";
  const mealCount=Number($("training_meal_claim_count").value||0);
  $("preview_meal").textContent=training
    ? `25,000원/일 · 교육훈련기관 청구 ${mealCount}식만큼 1/3 감액`
    : "25,000원/일 · 제공식 1식당 1/3 감액";
}

[$("vehicle_type"),$("phev_energy_source")].forEach(el=>el.addEventListener('change',updateVehicle));
[$("trip_type"),$("round_trip")].forEach(el=>el.addEventListener('change',()=>{updateTripType();updatePreview();}));
[$("travel_date"),$("end_date")].forEach(el=>el.addEventListener('change',()=>{populateTrainingMealCounts();updateTripType();updatePreview();}));
[$("training_stay_mode"),$("training_round_trips")].forEach(el=>el.addEventListener('change',updateTraining));
$("training_meal_claim_count").addEventListener('change',updatePreview);

const today=new Date().toISOString().slice(0,10);
$("travel_date").value=today;
$("end_date").value=today;
populateTrainingMealCounts();
updateVehicle();
updateTripType();

function basePayload(){
  const type=$("vehicle_type").value, spec=currentVehicleSpec();
  return {
    travel_date:$("travel_date").value,
    end_date:$("end_date").value,
    origin:$("origin").value,
    destination:$("destination").value,
    purpose:$("purpose").value||null,
    vehicle_type:type,
    phev_energy_source:type==="phev"?$("phev_energy_source").value:null,
    efficiency:spec.efficiency,
    round_trip:$("round_trip").checked,
    trip_type:$("trip_type").value,
    public_vehicle:$("public_vehicle").checked,
    provided_meals_count:Number($("provided_meals_count").value||0),
    training_stay_mode:$("training_stay_mode").value,
    training_round_trips:$("trip_type").value==="training"&&$("training_stay_mode").value==="custom"?Number($("training_round_trips").value||1):null,
    training_meal_claim_count:Number($("training_meal_claim_count").value||0),
    toll_fee:Number($("toll_fee").value||0),
    parking_fee:Number($("parking_fee").value||0),
    lodging_fee:Number($("lodging_fee").value||0),
    affiliation:$("affiliation").value||null,
    position:$("position").value||null,
    traveler_name:$("traveler_name").value||null
  };
}

function placeText(name,address){
  if(!name&&!address)return"-";
  if(!name||name===address)return address||name;
  return `${name} · ${address}`;
}

$("distanceButton").addEventListener('click',async()=>{
  if(!$("travel_date").value||!$("end_date").value||$("origin").value.trim().length<2||$("destination").value.trim().length<2){
    $("globalStatus").textContent="출장일과 출발지·출장지를 확인해주세요.";
    return;
  }
  $("distanceButton").disabled=true;
  $("globalStatus").textContent="기관명·주소 확인 및 거리 계산 중...";
  try{
    const payload=basePayload();
    const r=await fetch('/api/distance',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    const data=await r.json();
    if(!r.ok) throw new Error(data.detail||'거리 계산 실패');
    lastDistance=data;
    $("resolved_origin").textContent=placeText(data.resolved_origin_name,data.resolved_origin_address);
    $("resolved_destination").textContent=placeText(data.resolved_destination_name,data.resolved_destination_address);
    $("one_way_distance").textContent=`${fmt(data.one_way_distance_km)} km`;
    $("distance_source").textContent=data.distance_source+(data.distance_cache_hit?' · 캐시':'');
    $("destination_code").textContent=data.destination_support_office||data.destination_code||data.sigungu||'-';
    $("tab1check").textContent='✓';
    $("globalStatus").textContent="거리 확인 완료 · 여비 상세를 입력해주세요.";
    setTab(2);
  }catch(e){
    $("globalStatus").textContent=e.message;
  }finally{
    $("distanceButton").disabled=false;
  }
});

$("calculateButton").addEventListener('click',async()=>{
  if(!lastDistance){
    $("globalStatus").textContent="먼저 1단계에서 거리를 확인해주세요.";
    setTab(1);
    return;
  }
  $("calculateButton").disabled=true;
  $("globalStatus").textContent="운임·일비·식비 계산 중...";
  try{
    const payload=basePayload();
    const pp={
      travel_date:payload.travel_date,
      end_date:payload.end_date,
      vehicle_type:payload.vehicle_type,
      phev_energy_source:payload.phev_energy_source,
      efficiency:payload.efficiency,
      distance_km:lastDistance.distance_km,
      one_way_distance_km:lastDistance.one_way_distance_km,
      round_trip:payload.round_trip,
      province:lastDistance.province,
      sigungu:lastDistance.sigungu,
      origin_sigungu:lastDistance.origin_sigungu,
      trip_type:payload.trip_type,
      public_vehicle:payload.public_vehicle,
      provided_meals_count:payload.provided_meals_count,
      training_stay_mode:payload.training_stay_mode,
      training_round_trips:payload.training_round_trips,
      training_meal_claim_count:payload.training_meal_claim_count,
      toll_fee:payload.toll_fee,
      parking_fee:payload.parking_fee,
      lodging_fee:payload.lodging_fee
    };
    const r=await fetch('/api/price',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(pp)});
    const data=await r.json();
    if(!r.ok) throw new Error(data.detail||'여비 계산 실패');

    lastPayload=payload;
    $("final_origin").textContent=placeText(lastDistance.resolved_origin_name,lastDistance.resolved_origin_address);
    $("final_destination").textContent=placeText(lastDistance.resolved_destination_name,lastDistance.resolved_destination_address);
    $("final_one_way").textContent=`${fmt(lastDistance.one_way_distance_km)} km`;
    $("final_round_trips").textContent=data.round_trip_count===0.5?'편도':`${fmt(data.round_trip_count)}회`;
    $("final_transport_distance").textContent=`${fmt(data.transport_distance_km)} km`;
    $("vehicle_spec").textContent=`${data.vehicle_label||currentVehicleSpec().label} · ${data.effective_efficiency||currentVehicleSpec().efficiency} ${data.efficiency_unit||currentVehicleSpec().unit}`;
    $("fuel_price_date").textContent=data.fuel_price_date?`${data.fuel_price_date} · 출장 첫째 날`:'-';
    $("price").textContent=data.energy_price==null?'연결 예정':`${fmt(data.energy_price)} 원`;
    $("formula").textContent=data.calculation_formula||'-';
    $("amount").textContent=data.estimated_transport_cost==null?'단가 연결 후 계산':`${fmt(data.estimated_transport_cost)} 원`;
    $("daily_allowance").textContent=`${fmt(data.daily_allowance)} 원`;
    $("daily_note").textContent=data.daily_note||'-';
    $("meal_allowance").textContent=`${fmt(data.meal_allowance)} 원`;
    $("meal_note").textContent=data.meal_note||'-';
    $("toll_result").textContent=`${fmt(data.toll_fee)} 원`;
    $("parking_result").textContent=`${fmt(data.parking_fee)} 원`;
    $("lodging_result").textContent=`${fmt(data.lodging_fee)} 원`;
    $("total_expense").textContent=data.total_expense==null?'자동차 단가 연결 후 확정':`${fmt(data.total_expense)} 원`;
    $("source").textContent=(data.price_source||'-')+(data.price_cache_hit?' · 캐시':'');

    const spec=currentVehicleSpec();
    const canEvidence=spec.evidence&&data.energy_price!=null&&!payload.public_vehicle;
    if(canEvidence){
      lastEvidencePayload={travel_date:payload.travel_date,vehicle_type:spec.evidence,province:lastDistance.province,sigungu:lastDistance.sigungu,expected_price:data.energy_price};
      $("evidenceButton").disabled=false;
      $("evidence").textContent='API 가격 확인 · 증빙 생성 대기';
    }else{
      $("evidenceButton").disabled=true;
      $("evidence").textContent=data.evidence_status;
    }
    $("pdfButton").disabled=false;
    $("tab2check").textContent='✓';
    $("globalStatus").textContent="여비 계산 완료";
    setTab(3);
  }catch(e){
    $("globalStatus").textContent=e.message;
  }finally{
    $("calculateButton").disabled=false;
  }
});

$("evidenceButton").addEventListener('click',async()=>{
  if(!lastEvidencePayload)return;
  $("evidenceButton").disabled=true;
  const old=$("evidenceButton").textContent;
  $("evidenceButton").textContent='증빙 생성 중...';
  $("globalStatus").textContent='오피넷 증빙 화면 생성 중...';
  try{
    const r=await fetch('/api/opinet-evidence.png',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(lastEvidencePayload)});
    if(!r.ok){const d=await r.json();throw new Error(d.detail||'증빙 생성 실패');}
    const blob=await r.blob(),url=URL.createObjectURL(blob),a=document.createElement('a');
    a.href=url;
    a.download=`오피넷증빙_${lastEvidencePayload.travel_date}_${lastEvidencePayload.sigungu}.png`;
    a.click();
    setTimeout(()=>URL.revokeObjectURL(url),1000);
    $("evidence").textContent='verified_web_capture';
    $("globalStatus").textContent='증빙 생성 완료';
  }catch(e){
    $("evidence").textContent='evidence_failed';
    $("globalStatus").textContent=`증빙 생성 실패 · ${e.message}`;
  }finally{
    $("evidenceButton").textContent=old;
    $("evidenceButton").disabled=false;
  }
});

$("pdfButton").addEventListener('click',async()=>{
  if(!lastPayload)return;
  $("pdfButton").disabled=true;
  const old=$("pdfButton").textContent;
  $("pdfButton").textContent='PDF 생성 중...';
  try{
    const r=await fetch('/api/report.pdf',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(lastPayload)});
    if(!r.ok){const d=await r.json();throw new Error(d.detail||'PDF 생성 실패');}
    const blob=await r.blob(),url=URL.createObjectURL(blob),a=document.createElement('a');
    a.href=url;
    a.download=`여비산출내역_${lastPayload.travel_date}.pdf`;
    a.click();
    setTimeout(()=>URL.revokeObjectURL(url),1000);
  }catch(e){
    $("globalStatus").textContent=e.message;
  }finally{
    $("pdfButton").textContent=old;
    $("pdfButton").disabled=false;
  }
});
