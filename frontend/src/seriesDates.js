// Python weekdays: Monday=0. Work with local date parts, never UTC conversion.
export function firstSeriesDate(start, end, weekdays) {
  if(!start||!end||start>end||!weekdays?.length)return null;
  const day=new Date(`${start}T12:00:00`);
  for(let i=0;i<7;i++,day.setDate(day.getDate()+1)){
    const value=`${day.getFullYear()}-${String(day.getMonth()+1).padStart(2,'0')}-${String(day.getDate()).padStart(2,'0')}`;
    if(value>end)return null;
    if(weekdays.includes((day.getDay()+6)%7))return value;
  }
  return null;
}
