export const EVENT_FORMAT_OPTIONS=['ДПП ПК','ДПП ПП','Семинар','Другое'];

export function eventFormatState(value=''){
  const clean=String(value||'').trim();
  if(!clean)return {event_format_choice:'',event_format_other:''};
  if(EVENT_FORMAT_OPTIONS.includes(clean))return {event_format_choice:clean,event_format_other:''};
  return {event_format_choice:'Другое',event_format_other:clean};
}

export function eventFormatReady(form){
  return Boolean(form.event_format_choice&&(
    form.event_format_choice!=='Другое'||String(form.event_format_other||'').trim().length>=2
  ));
}

export function eventFormatValue(form){
  return form.event_format_choice==='Другое'
    ?String(form.event_format_other||'').trim()
    :String(form.event_format_choice||'').trim();
}

export default function EventFormatField({form,update,attempted=false,invalid=false}){
  const ready=eventFormatReady(form);
  const state=ready?'complete':attempted||invalid?'invalid':'';
  return <>
    <label className={`event-format-field ${state}`}>
      <span>Формат мероприятия *</span>
      <select value={form.event_format_choice||''} onChange={event=>{
        update('event_format_choice',event.target.value);
        if(event.target.value!=='Другое')update('event_format_other','');
      }}>
        <option value="" disabled>Выберите формат</option>
        {EVENT_FORMAT_OPTIONS.map(option=><option value={option} key={option}>{option}</option>)}
      </select>
    </label>
    {form.event_format_choice==='Другое'&&<label className={`event-format-field event-format-custom ${state}`}>
      <span>Собственный формат мероприятия *</span>
      <input value={form.event_format_other||''} maxLength={120} onChange={event=>update('event_format_other',event.target.value)} placeholder="Укажите формат мероприятия"/>
    </label>}
  </>;
}
