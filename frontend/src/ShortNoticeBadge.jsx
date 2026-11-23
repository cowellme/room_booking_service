import {Clock3} from 'lucide-react';

export default function ShortNoticeBadge({item}) {
  const dates=item.series_items;
  if(dates ? !dates.some(entry=>entry.short_notice) : !item.short_notice)return null;

  return <p className="short-notice-badge">
    <Clock3 aria-hidden="true"/>
    <span>{dates?'В серии есть даты с подачей менее чем за 7 рабочих дней':'Оформлено менее чем за 7 рабочих дней до мероприятия'}</span>
  </p>;
}
