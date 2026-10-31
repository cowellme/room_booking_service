import {useEffect,useState} from 'react';
import {HelpCircle, X} from 'lucide-react';
import './extraRoomsGuide.css';

export default function ExtraRoomsGuide({request,count=0,variant='single'}){
  const [open,setOpen]=useState(false);
  const [saving,setSaving]=useState(false);
  const [error,setError]=useState('');
  useEffect(()=>{let active=true;request('/api/profile/extra-rooms-guide').then(data=>{if(active&&data?.seen===false)setOpen(true)}).catch(()=>{});return()=>{active=false}},[request]);
  const remember=async()=>{setSaving(true);setError('');try{await request('/api/profile/extra-rooms-guide/seen',{method:'POST'});setOpen(false)}catch{setError('Не удалось сохранить настройку. Попробуйте ещё раз или закройте подсказку на этот раз.')}finally{setSaving(false)}};
  const series=variant==='series';
  return <div className="extra-guide">
    <div className="extra-guide-bar"><span>{series?`Выбрано аудиторий: ${count}`:count?`Основная аудитория + дополнительные: ${count}`:'Можно добавить другие аудитории к этой заявке'}</span><button type="button" className="extra-guide-help" onClick={()=>{setError('');setOpen(true)}}><HelpCircle/>Как добавить?</button></div>
    {open&&<aside className="extra-guide-card" aria-label="Как добавить аудитории"><button type="button" className="extra-guide-close" aria-label="Закрыть подсказку на этот раз" onClick={()=>setOpen(false)} disabled={saving}><X/></button><strong>Нужно больше одной аудитории?</strong>{series?<><p>Выберите здесь все аудитории, которые нужны на каждую дату серии.</p><p>Отдельное назначение для каждой аудитории можно указать в обычной заявке; для серии эту возможность пока не добавили.</p></>:<><p>Добавьте помещения для этого мероприятия и укажите назначение каждого: например, регистрация, хранение вещей или питание.</p><ol><li>Нажмите «Добавить аудиторию».</li><li>Выберите свободное помещение и укажите его назначение.</li></ol><small>Аудитории будут отправлены вместе с основной заявкой.</small></>}{error&&<p className="extra-guide-error" role="alert">{error}</p>}<div className="extra-guide-actions"><button type="button" className="primary" onClick={remember} disabled={saving}>{saving?'Сохраняем…':'Понятно, больше не показывать'}</button><button type="button" className="extra-guide-skip" onClick={()=>setOpen(false)} disabled={saving}>Не сейчас</button></div></aside>}
  </div>
}
