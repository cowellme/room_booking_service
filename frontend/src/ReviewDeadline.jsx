import './bookingQuestions.css';

export default function ReviewDeadline({item}) {
  if(item.review_expired)return <div className="review-deadline expired">Не подтверждена · истёк срок рассмотрения · архив</div>;
  if(item.status!=='pending'||!item.review_deadline)return null;
  const deadline=new Date(item.review_deadline).toLocaleString('ru-RU',{day:'2-digit',month:'2-digit',year:'numeric',hour:'2-digit',minute:'2-digit',timeZone:'Europe/Moscow'});
  return <div className={`review-deadline ${item.review_urgent?'urgent':''}`} role="status">
    <strong>{item.review_overdue?'Срок рассмотрения истёк':`До решения: ${item.review_days_left} раб. дн.`}</strong>
    <span>Рассмотреть до {deadline} (МСК)</span>
  </div>;
}
