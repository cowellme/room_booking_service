export const STATUS_LABELS={
  pending:'Ожидает решения',approved:'Подтверждено',rejected:'Отклонено',cancelled:'Отменено',
  cancelled_by_user:'Отменено пользователем',cancelled_by_admin:'Отменено администратором',
  completed:'Состоялось',no_show:'Неявка',
  transferred:'Перенесено',
};

export const SOURCE_LABELS={
  phone:'Оформлено по звонку',admin_direct:'Оформлено администратором',
  self_service:'Заявка пользователя',
  admin_batch:'Серия бронирований',transfer:'Перенос бронирования',service_block:'Служебная блокировка',excel_import:'Импортировано из Excel',
};

export const CLOSED_BOOKING_STATUSES=[
  'rejected','cancelled','cancelled_by_user','cancelled_by_admin','completed','no_show','transferred',
];

// Local calendar date: toISOString() would return yesterday during the first hours after midnight.
export const localIso=(value=new Date())=>`${value.getFullYear()}-${String(value.getMonth()+1).padStart(2,'0')}-${String(value.getDate()).padStart(2,'0')}`;
export const todayIso=()=>localIso();
// Russian plural form: plural(21, ['запись','записи','записей']) → 'запись'.
export const plural=(n,[one,few,many])=>n%10===1&&n%100!==11?one:n%10>=2&&n%10<=4&&(n%100<12||n%100>14)?few:many;

// UI hint only: the backend independently checks the institution clock.
export const eventFinished=(item,now=new Date())=>{
  const end=new Date(`${item.date}T${item.time_end}`);
  return Number.isFinite(end.getTime())&&now.getTime()>=end.getTime();
};

export const formatDepartmentCode=code=>
  /^USER-[A-F0-9]{10}$/i.test(code||'')?'Добавлено пользователем':code;

export const formatBookingDate=value=>new Date(`${value}T00:00:00`).toLocaleDateString(
  'ru-RU',{day:'numeric',month:'long',year:'numeric'},
);

export const formatBookingMoment=value=>value
  ?new Date(value).toLocaleString('ru-RU',{day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit',hour12:false})
  :'—';

export const groupSeriesItems=items=>{const groups=new Map();for(const item of items){const key=item.series_id?'series:'+item.series_id:'item:'+item.id;if(!groups.has(key))groups.set(key,[]);groups.get(key).push(item)}return [...groups.values()].map(group=>{group.sort((a,b)=>String(a.date+' '+a.time_start).localeCompare(String(b.date+' '+b.time_start)));const first=group[0];return group.length===1?first:{...first,series_items:group,series_count:group.length,series_dates:[group[0].date,group[group.length-1].date]}})};

// Unfinished admin booking forms survive page switches and reloads (per browser, per administrator).
export const readStored=key=>{try{return JSON.parse(localStorage.getItem(key)||'null')}catch{return null}};
export const writeStored=(key,value)=>{try{if(value==null)localStorage.removeItem(key);else localStorage.setItem(key,JSON.stringify(value))}catch{}};
export const readDraft=(key,token)=>{const value=key?readStored(key):null;return value&&value.token===token?value:null};
