import {bookingPeriodLabel} from './bookingDates';
import {useEffect, useMemo, useRef, useState} from 'react';
import {AlertCircle, Building2, Check, Clock3, Plus, RotateCcw, Search, Trash2, Users, X} from 'lucide-react';
import './adminExtraRooms.css';
import ExtraRoomsGuide from './ExtraRoomsGuide';

const TTL=60000;
const OTHER='__other';
const purposeText=row=>((row.purpose===OTHER?row.purpose_other:row.purpose)||'').trim();

function RoomPhoto({room}){
  const [failed,setFailed]=useState(false);
  const src=room?.images?.[0]||room?.building_image;
  return src&&!failed?<img src={src} alt="" onError={()=>setFailed(true)}/>:<div className="aer-photo-placeholder"><Building2/></div>;
}

export default function AdminExtraRoomsPicker({request,availabilityUrl,date,dateEnd=date,timeStart,timeEnd,mainRoomId,value,onChange,attempted,roomCatalog=[],purposes,maxRooms}){
  const [cache,setCache]=useState({});
  const cacheRef=useRef({});
  const inFlight=useRef(new Set());
  const mounted=useRef(false);
  const [refresh,setRefresh]=useState(0);
  const [editor,setEditor]=useState(null);
  const [chosenInfo,setChosenInfo]=useState({});
  const [highlighted,setHighlighted]=useState(-1);
  const root=useRef(null),catalog=useRef(null),searchInput=useRef(null);
  const ready=Boolean(date&&dateEnd>=date&&mainRoomId);
  useEffect(()=>{mounted.current=true;return()=>{mounted.current=false}},[]);
  useEffect(()=>{if(!ready)return;const timer=setInterval(()=>setRefresh(v=>v+1),TTL);return()=>clearInterval(timer)},[ready]);
  const windowKey=JSON.stringify([date,dateEnd,timeStart||null,timeEnd||null]);
  useEffect(()=>{
    if(!ready)return;
    const key=windowKey;
    const entry=cacheRef.current[key];
    if(inFlight.current.has(key)||(entry&&Date.now()-entry.checkedAt<TTL))return;
    const put=data=>{if(!mounted.current)return;cacheRef.current={...cacheRef.current,[key]:data};setCache(cacheRef.current)};
    inFlight.current.add(key);
    put({status:'loading',rooms:[],checkedAt:0});
    const params={date,date_end:dateEnd,participants:1};
    // Adding to a historic booking preserves its saved hours, without showing time controls.
    if(timeStart&&timeEnd)Object.assign(params,{time_start:timeStart,time_end:timeEnd});
    request(availabilityUrl,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(params)})
      .then(result=>put({status:'ready',rooms:result.free||[],checkedAt:Date.now()}))
      .catch(error=>put({status:'error',rooms:[],checkedAt:Date.now(),message:error.message||'Не удалось проверить занятость'}))
      .finally(()=>inFlight.current.delete(key));
  },[ready,windowKey,refresh,availabilityUrl,request]);
  useEffect(()=>{if(!editor)return;catalog.current?.scrollIntoView({behavior:'smooth',block:'nearest'});searchInput.current?.focus({preventScroll:true})},[editor?.index,Boolean(editor)]);
  useEffect(()=>{if(highlighted<0)return;const card=root.current?.querySelector(`[data-extra-index="${highlighted}"]`);card?.scrollIntoView({behavior:'smooth',block:'nearest'});card?.querySelector('select')?.focus({preventScroll:true});const timer=setTimeout(()=>setHighlighted(-1),1500);return()=>clearTimeout(timer)},[highlighted,value.length]);
  const info=useMemo(()=>{
    const map=new Map(Object.values(chosenInfo).map(room=>[String(room.id),room]));
    for(const room of roomCatalog)map.set(String(room.id),room);
    for(const entry of Object.values(cache))for(const room of entry.rooms)map.set(String(room.id),room);
    return map;
  },[chosenInfo,roomCatalog,cache]);
  const change=(index,patch)=>onChange(value.map((row,i)=>i===index?{...row,...patch}:row));
  const open=(index=null)=>{
    setHighlighted(-1);
    setEditor({index,search:'',building:''});
  };
  const remove=index=>{onChange(value.filter((_,i)=>i!==index));setEditor(current=>!current||current.index===index?null:current.index!==null&&current.index>index?{...current,index:current.index-1}:current)};
  const choose=room=>{
    const patch={room_id:String(room.id)};
    const index=editor.index===null?value.length:editor.index;
    if(editor.index===null){if(value.length>=maxRooms)return;onChange([...value,{purpose:'',purpose_other:'',...patch}])}else change(editor.index,patch);
    setChosenInfo(current=>({...current,[room.id]:room}));setEditor(null);setHighlighted(index);
  };
  const entry=cache[windowKey];
  const taken=new Set([String(mainRoomId),...value.filter((_,index)=>index!==editor?.index).map(row=>String(row.room_id))]);
  const options=(entry?.rooms||[]).filter(room=>!taken.has(String(room.id)));
  const buildings=[...new Map(options.map(room=>[String(room.building_id),room.building])).entries()].sort((a,b)=>a[1].localeCompare(b[1],'ru'));
  const query=editor?.search.trim().toLocaleLowerCase('ru')||'';
  const filtered=options.filter(room=>(!editor?.building||String(room.building_id)===editor.building)&&(!query||`${room.number} ${room.name||''} ${room.building}`.toLocaleLowerCase('ru').includes(query)));
  const retry=()=>{delete cacheRef.current[windowKey];setRefresh(v=>v+1)};
  if(!ready)return null;
  return <section className="extra-rooms admin-extra-rooms" ref={root} onKeyDown={event=>{if(editor&&event.key==='Escape'){event.preventDefault();event.stopPropagation();setEditor(null)}}}>
    <div className="extra-rooms-head"><div><b>Дополнительные аудитории{value.length>0&&<em>{value.length} / {maxRooms}</em>}</b><small>Если нужны другие помещения, добавьте их к основной брони и укажите назначение каждого.</small></div><button type="button" className="secondary" onClick={()=>open()} disabled={value.length>=maxRooms}><Plus/>Добавить аудиторию</button></div>
    <ExtraRoomsGuide request={request} count={value.length}/>
    {!value.length&&!editor&&<div className="aer-intro"><Building2/><span>Добавьте помещение — выберите его по фото, корпусу и вместимости.</span></div>}
    <div className="aer-selected-list">{value.map((row,index)=>{
      const room=info.get(String(row.room_id));
      const status=entry;
      const unavailable=status?.status==='ready'&&(!status.rooms.some(item=>String(item.id)===String(row.room_id))||String(row.room_id)===String(mainRoomId));
      return <article className={`aer-selected-card ${highlighted===index?'just-selected':''} ${attempted&&(!row.room_id||purposeText(row).length<2)?'invalid':''}`} data-extra-index={index} key={index} style={{'--aer-color':room?.color||'#007895'}}>
        <header><div className="aer-selected-photo"><RoomPhoto key={room?.id} room={room}/></div><div className="aer-selected-info"><small className="aer-building">{room?.building||'Дополнительная аудитория'}</small><h4>{room?`Аудитория ${room.number}`:'Выберите аудиторию'}</h4><span>{room?.capacity?`${room.capacity} мест · `:''}{room?.floor_display||(room?.floor?`${room.floor} этаж`:'')}</span></div><button type="button" className="aer-remove" aria-label={`Убрать аудиторию ${room?.number||index+1}`} onClick={()=>remove(index)}><Trash2/></button></header>
        <div className={`aer-selected-status ${unavailable||status?.status==='error'?'warning':''}`}>
          {unavailable||status?.status==='error'?<AlertCircle/>:status?.status==='ready'?<Check/>:<Clock3/>}
          <span>{unavailable?'Аудитория недоступна. Замените её или измените даты.':status?.status==='error'?'Не удалось проверить занятость. Откройте подбор и повторите проверку.':status?.status==='ready'?'Свободна на выбранные даты':'Проверяем занятость…'}</span>
        </div>
        <label className={purposeText(row).length>=2?'complete':attempted?'invalid':''}><span>Назначение *</span><select value={row.purpose} onChange={event=>change(index,{purpose:event.target.value})}><option value="">Для чего нужна аудитория?</option>{purposes.map(purpose=><option key={purpose}>{purpose}</option>)}<option value={OTHER}>Другое…</option></select>{row.purpose===OTHER&&<input value={row.purpose_other} maxLength={120} placeholder="Укажите назначение аудитории" onChange={event=>change(index,{purpose_other:event.target.value})}/>}</label>
        <footer><span><Clock3/>{bookingPeriodLabel(date,dateEnd)}</span><button type="button" onClick={()=>open(index)}><RotateCcw/>Заменить аудиторию</button></footer>
      </article>;
    })}</div>
    {editor&&<section className="aer-catalog" ref={catalog} aria-label="Подбор дополнительной аудитории">
      <header><div><small>{editor.index===null?'ДОБАВИТЬ К БРОНИ':'ЗАМЕНИТЬ АУДИТОРИЮ'}</small><h4>Выберите свободную аудиторию</h4></div><button type="button" className="aer-close" aria-label="Закрыть подбор аудиторий" onClick={()=>setEditor(null)}><X/></button></header>
      <div className="aer-filters"><label className="aer-search"><span>Поиск аудитории</span><div><Search/><input ref={searchInput} value={editor.search} placeholder="Номер или название" onChange={event=>setEditor({...editor,search:event.target.value})}/></div></label><label><span>Корпус</span><select value={editor.building} onChange={event=>setEditor({...editor,building:event.target.value})}><option value="">Все корпуса</option>{buildings.map(([id,name])=><option value={id} key={id}>{name}</option>)}</select></label></div>
      {!entry||entry.status==='loading'?<p className="aer-empty" role="status"><Clock3/>Проверяем свободные аудитории…</p>:entry.status==='error'?<div className="aer-empty error" role="alert"><AlertCircle/><span>{entry.message}</span><button type="button" onClick={retry}>Повторить проверку</button></div>:<>
        <div className="aer-results-heading"><span>Доступно: {filtered.length}</span><small>{bookingPeriodLabel(date,dateEnd)}</small></div>
        <div className="aer-catalog-grid">{filtered.map(room=><article className="aer-option" key={room.id} style={{'--aer-color':room.color||'#007895'}}><div className="aer-option-photo"><RoomPhoto room={room}/><span><Check/>Свободна</span></div><div className="aer-option-body"><small className="aer-building">{room.building}</small><h4>Аудитория {room.number}</h4><p><Users/>{room.capacity} мест<span>{room.floor_display||(room.floor?`${room.floor} этаж`:'')}</span></p><button type="button" className="primary" onClick={()=>choose(room)}>Выбрать</button></div></article>)}</div>
        {!filtered.length&&<div className="aer-empty"><Search/><b>Подходящих аудиторий нет</b><span>Измените поиск, корпус или даты.</span>{(editor.search||editor.building)&&<button type="button" onClick={()=>setEditor({...editor,search:'',building:''})}>Сбросить поиск и корпус</button>}</div>}
      </>}
    </section>}
  </section>;
}
