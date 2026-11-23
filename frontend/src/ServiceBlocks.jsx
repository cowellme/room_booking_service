import {Check} from 'lucide-react';
import {useEffect,useState} from 'react';
import {localIso} from './bookingCenterConfig';

const kinds={maintenance:'Ремонт',setup:'Монтаж / застройка',teardown:'Демонтаж',unavailable:'Другая недоступность'};
const statuses={approved:'Подтверждена',previous:'Прошла',cancelled:'Отменена',cancelled_by_admin:'Отменена',cancelled_by_user:'Отменена'};
const formatDate=value=>value.split('-').reverse().join('.');
export function BlocksPage({rooms,request,changed}){
  const [items,setItems]=useState(null),[error,setError]=useState(''),[open,setOpen]=useState(false),[revision,setRevision]=useState(0);
  useEffect(()=>{let active=true;request('/api/admin/service-blocks').then(data=>{if(active)setItems(data)}).catch(err=>{if(active)setError(err.message)});return()=>{active=false}},[request,revision]);
  return <section className="content-page moderation-page"><div className="page-heading"><div><small>ТЕХНИЧЕСКИЕ РАБОТЫ</small><h1>Блокировка аудитории</h1><p>Ремонт, монтаж и демонтаж. Блокировки занимают выбранные даты в календаре.</p></div><button className="primary" onClick={()=>setOpen(true)}>Оформить блокировку</button></div>
    {error&&<p className="error" role="alert">{error}</p>}
    <div className="blocks-list">{items?.map(item=><article key={item.id} className={'service-block '+item.record_kind}><strong>{kinds[item.record_kind]} · {item.title}</strong><p>{item.building} · аудитория {item.room_number}</p><small>{formatDate(item.date)} · {item.status==='approved'&&item.date<localIso()?statuses.previous:statuses[item.status]||item.status}</small></article>)}</div>
    {!error&&(!items?<p>Загружаем блокировки…</p>:items.length===0&&<p>Блокировок пока нет.</p>)}
    {open&&<BlockActionDialog rooms={rooms} request={request} close={()=>setOpen(false)} done={()=>{setOpen(false);setError('');setRevision(x=>x+1);changed()}}/>}
  </section>;
}

export function BlockActionDialog({initial,rooms,request,close,done}){
  const [saving,setSaving]=useState(false),[error,setError]=useState('');
  const today=localIso();
  const [start,setStart]=useState(initial?.day||today),[end,setEnd]=useState(initial?.day||today);
  const submit=async event=>{
    event.preventDefault();
    if(saving)return;
    const form=Object.fromEntries(new FormData(event.currentTarget));
    const {room_id,...fields}=form;
    setSaving(true);setError('');
    try{await request('/api/admin/service-blocks',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...fields,reason:form.title,room_ids:[Number(initial?.room.id||room_id)]})});done()}
    catch(err){setError(err.message);setSaving(false)}
  };
  return <div className="center-modal nested"><button className="center-backdrop" aria-label="Закрыть" onClick={()=>!saving&&close()}/><section className="operation-dialog" role="dialog" aria-modal="true" aria-labelledby="block-action-title"><header><div><small>КАЛЕНДАРЬ АУДИТОРИЙ</small><h2 id="block-action-title">Оформить блокировку</h2></div><button className="icon" aria-label="Закрыть" disabled={saving} onClick={close}>×</button></header>
    <form className="operation-form" onSubmit={submit}>
      {initial?<div className="full user-preselected-room" style={{'--room-color':'var(--vshgu-action, #017cbf)'}}>{initial.room.images?.[0]&&<img src={initial.room.images[0]} alt=""/>}<span><small>ВЫБРАННАЯ АУДИТОРИЯ</small><b>{initial.room.building} · аудитория {initial.room.number}</b><em>{initial.room.name} · {initial.room.capacity} мест</em></span><Check aria-hidden="true"/></div>:<label className="full"><span>Аудитория *</span><select name="room_id" required defaultValue=""><option value="" disabled>Выберите аудиторию</option>{rooms.map(room=><option key={room.id} value={room.id}>{room.building} · {room.number}</option>)}</select></label>}
      <label><span>Дата начала *</span><input name="date" type="date" required value={start} onChange={e=>{setStart(e.target.value);if(end<e.target.value)setEnd(e.target.value)}}/></label>
      <label><span>Дата окончания *</span><input name="date_end" type="date" min={start||undefined} required value={end} onChange={e=>setEnd(e.target.value)}/></label>
      <label className="full"><span>Вид блокировки *</span><select name="record_kind" required defaultValue="maintenance">{Object.entries(kinds).filter(([key])=>key!=='unavailable').map(([key,text])=><option value={key} key={key}>{text}</option>)}</select></label>
      <label className="full"><span>Название мероприятия *</span><input name="title" required minLength={2} maxLength={200}/></label>
      {error&&<p className="error full" role="alert">{error}</p>}
      <footer className="full"><button type="button" className="secondary" onClick={close} disabled={saving}>Отмена</button><button className="primary" disabled={saving}>{saving?'Сохраняем…':'Оформить блокировку'}</button></footer>
    </form>
  </section></div>;
}
