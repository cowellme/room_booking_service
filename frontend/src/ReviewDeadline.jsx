import './bookingQuestions.css';

export default function ReviewDeadline({item}) {
  return item.review_expired
    ? <div className="review-deadline expired">Не подтверждена · истёк прежний срок рассмотрения · архив</div>
    : null;
}
