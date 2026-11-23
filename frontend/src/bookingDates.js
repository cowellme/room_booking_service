import {formatBookingDate} from './bookingCenterConfig';

export const bookingDatesReady=({date,date_end})=>Boolean(date&&date_end&&date_end>=date);
export const bookingPeriodLabel=(date,end=date)=>date===end?formatBookingDate(date):`${formatBookingDate(date)} — ${formatBookingDate(end)}`;
export function changeBookingDate(form,key,value){
  if(key!=='date')return {...form,[key]:value};
  const followStart=value&&(!form.date_end||form.date_end===form.date||form.date_end<value);
  return {...form,date:value,date_end:followStart?value:form.date_end};
}
