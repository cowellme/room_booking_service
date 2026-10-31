import {useId} from 'react';
import './bookingQuestions.css';

export default function BookingQuestions({form, update, attempted=false}) {
  const id=useId();
  return <div className="full booking-required-questions">{[
    ['catering','Требуется аудитория для организации питания?'],
    ['technical_support','Заявка на материально-техническое обеспечение требуется?'],
  ].map(([key,label])=><fieldset key={key} className={`booking-required-question ${form[key]?'answered':attempted?'unanswered':''}`} aria-invalid={attempted&&!form[key]}>
    <legend>{label} *</legend>
    {['yes','no'].map(value=><label key={value}><input type="radio" name={`${id}-${key}`} checked={form[key]===value} onChange={()=>update(key,value)}/>{value==='yes'?'Да':'Нет'}</label>)}
    {attempted&&!form[key]&&<small role="alert">Выберите «Да» или «Нет»</small>}
  </fieldset>)}</div>;
}
