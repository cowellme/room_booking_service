import {Wrench} from 'lucide-react';

export function BookingSetupNotice({className=''}){
  return <p className={`booking-setup-notice ${className}`}>Застройка выполняется сотрудником административно-организационного отдела.</p>
}

export default function RoomEquipmentBlock({rooms=[],className=''}){
  const selected=rooms.filter(Boolean);
  return <><BookingSetupNotice className={className}/><div className={`room-equipment-block ${className}`}><header><Wrench/><b>Техническое оснащение</b><small>{selected.length>1?'Что есть в выбранных аудиториях':'Что есть в выбранной аудитории'}</small></header>{selected.length?selected.map(room=><div className="room-equipment-item" key={room.id}>{selected.length>1&&<strong>Ауд. {room.number}</strong>}{(room.equipment||[]).length?<div className="equipment">{room.equipment.map(item=><span key={item}>{item}</span>)}</div>:<p>Оснащение аудитории не указано.</p>}</div>):<p>Выберите аудиторию — здесь появится её оснащение.</p>}</div></>
}
