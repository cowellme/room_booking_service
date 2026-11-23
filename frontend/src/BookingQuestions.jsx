import {useId,useState} from 'react';
import './bookingQuestions.css';

const LOCATIONS=[
  ['moscow_campus','Московский кампус'],
  ['remote_site','Удалённая территория'],
];
const YES_NO=[[true,'Да'],[false,'Нет']];
const QUESTIONS=[
  ['event_location','Где планируется проведение мероприятия?',LOCATIONS],
  ['catering_required','Требуется аудитория для организации питания?',YES_NO],
  ['catering_storage_required','Требуется аудитория под склад кейтеринга?',YES_NO],
  ['operations_hq_required','Требуется аудитория для оперативного штаба?',YES_NO],
  ['vip_room_required','Требуется комната для VIP-гостей?',YES_NO],
];
const PYRUS_URL='https://pyrus.com/t#uf1377721';
const validAnswer=(form,key,options)=>options.some(([value])=>form?.[key]===value);

export const missingBookingQuestions=form=>QUESTIONS.filter(([key,,options])=>!validAnswer(form,key,options)).map(([key])=>key);
export const bookingQuestionAnswers=(form={})=>Object.fromEntries(QUESTIONS.map(([key,,options])=>[key,validAnswer(form,key,options)?form[key]:null]));

export function BookingQuestionSummary({item}) {
  return <dl className="booking-question-summary">{QUESTIONS.map(([key,label,options])=><div key={key}>
    <dt>{label}</dt><dd>{options.find(([value])=>value===item[key])?.[1]??'Не указано'}</dd>
  </div>)}</dl>;
}

export default function BookingQuestions({form, update, attempted=false}) {
  const id=useId();
  const [showPyrus,setShowPyrus]=useState(false);
  return <div className="full booking-required-questions">
    {QUESTIONS.map(([key,label,options])=>{
      const answered=validAnswer(form,key,options);
      const invalid=attempted&&!answered;
      return <fieldset key={key} className={`booking-required-question ${key==='event_location'?'booking-location-question ':''}${answered?'answered':invalid?'unanswered':''}`} aria-invalid={invalid||undefined} aria-describedby={invalid?`${id}-${key}-error`:undefined}>
        <legend>{label} *</legend>
        {key==='event_location'
          ? <select aria-label={label} value={form[key]??''} onChange={event=>update(key,event.target.value)} required>
              <option value="" disabled>Выберите место проведения</option>
              {options.map(([value,text])=><option key={value} value={value}>{text}</option>)}
            </select>
          : options.map(([value,text])=><label key={text}>
              <input type="radio" name={`${id}-${key}`} checked={form[key]===value} onChange={()=>update(key,value)} required/>{text}
            </label>)}
        {invalid&&<small id={`${id}-${key}-error`} role="alert">{key==='event_location'?'Выберите место проведения':'Выберите «Да» или «Нет»'}</small>}
      </fieldset>;
    })}
    <div className="booking-pyrus">
      <label className="booking-pyrus-toggle">
        <input type="checkbox" checked={showPyrus} onChange={event=>setShowPyrus(event.target.checked)} aria-controls={`${id}-pyrus-link`}/>
        <span><strong>Сделать заявку на материально-техническое обеспечение</strong>
          <small>(обеспечение канцелярскими/программными принадлежностями для проведения образовательных программ)</small>
        </span>
      </label>
      <p id={`${id}-pyrus-link`} hidden={!showPyrus}>
        <strong>Ссылка на заявку:</strong> <a href={PYRUS_URL} target="_blank" rel="noopener noreferrer">{PYRUS_URL}</a>
      </p>
    </div>
  </div>;
}
