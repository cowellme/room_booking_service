import { createContext, useContext, useEffect, useMemo, useRef, useState } from 'react';
import { BarChart3, ChevronDown, Download, HelpCircle, Printer, RefreshCw } from 'lucide-react';
import { localIso } from './bookingCenterConfig';
import './analytics.css';
import analyticsCss from './analytics.css?raw';

// Categorical slots in fixed order (validated palette); "Другие" / "Не указано" always take the neutral slot.
const SLOTS = 8;
const OTHER_LABELS = new Set(['Другие', 'Не указано', 'Не указан']);
const DONUT_LIMIT = 10;
const AnalyticsFullView = createContext(false);

const PRESETS = [
  ['7', 'Последние 7 дней'],
  ['30', 'Последние 30 дней'],
  ['month', 'Текущий месяц'],
  ['prev-month', 'Прошлый месяц'],
  ['quarter', 'Последние 90 дней'],
  ['year', 'Последние 12 месяцев'],
];

function presetRange(key) {
  const today = new Date();
  const back = days => localIso(new Date(today.getFullYear(), today.getMonth(), today.getDate() - days + 1));
  if (key === 'month') return [localIso(new Date(today.getFullYear(), today.getMonth(), 1)), localIso(today)];
  if (key === 'prev-month') return [
    localIso(new Date(today.getFullYear(), today.getMonth() - 1, 1)),
    localIso(new Date(today.getFullYear(), today.getMonth(), 0)),
  ];
  if (key === 'quarter') return [back(90), localIso(today)];
  if (key === 'year') return [back(365), localIso(today)];
  return [back(Number(key)), localIso(today)];
}

const formatDate = value => new Date(`${value}T00:00:00`).toLocaleDateString('ru-RU', { day: 'numeric', month: 'long', year: 'numeric' });
const formatShortDate = value => new Date(`${value}T00:00:00`).toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit' });
const formatNumber = value => Number(value).toLocaleString('ru-RU');

function formatDuration(minutes) {
  if (minutes === null || minutes === undefined) return '—';
  const hours = Math.floor(minutes / 60);
  const rest = Math.round(minutes % 60);
  if (!hours) return `${rest} мин`;
  return rest ? `${formatNumber(hours)} ч ${rest} мин` : `${formatNumber(hours)} ч`;
}

// Keep the largest categories, fold the tail into one neutral "Другие" slice.
function foldTail(rows, limit = DONUT_LIMIT) {
  const visible = rows.filter(row => row.value > 0);
  if (visible.length <= limit) return visible;
  const head = visible.slice(0, limit);
  const rest = visible.slice(limit).reduce((sum, row) => sum + row.value, 0);
  return [...head, { label: 'Другие', value: rest }];
}

function colorClass(rows) {
  let slot = 0;
  return rows.map(row => (OTHER_LABELS.has(row.label) ? 'slot-other' : `slot-${(slot++ % SLOTS) + 1}`));
}

function useTooltip() {
  const [tip, setTip] = useState(null);
  const show = (event, text) => {
    const box = event.currentTarget.closest('.analytics-card').getBoundingClientRect();
    setTip({ x: event.clientX - box.left, y: event.clientY - box.top, text });
  };
  const hide = () => setTip(null);
  const node = tip && <div className="analytics-tooltip" style={{ left: tip.x, top: tip.y }}>{tip.text}</div>;
  return { show, hide, node };
}

function Card({ title, subtitle, wide = false, help = null, children }) {
  const [open, setOpen] = useState(true);
  const tooltip = useTooltip();
  const [details, setDetails] = useState(false);
  useEffect(() => {
    if (!details) return;
    const close = event => { if (event.key === 'Escape') setDetails(false); };
    document.addEventListener('keydown', close);
    return () => document.removeEventListener('keydown', close);
  }, [details]);
  return (
    <section className={`analytics-card ${wide ? 'wide' : ''} ${open ? '' : 'collapsed'}`}>
      <header>
        <div>
          <h2>{title}</h2>
          {subtitle && <small>{subtitle}</small>}
        </div>
        <div className="analytics-card-actions">{help}{!wide && <button type="button" className="analytics-details-button no-export" onClick={() => setDetails(true)}>Все данные</button>}<button type="button" className="analytics-collapse no-export" onClick={() => setOpen(!open)} aria-label={open ? 'Свернуть' : 'Развернуть'}>
          <ChevronDown />
        </button></div>
      </header>
      <div className="analytics-card-body">{typeof children === 'function' ? children(tooltip) : children}</div>
      {tooltip.node}
      {details && <div className="analytics-details-backdrop no-export" onClick={() => setDetails(false)}>
        <section className="analytics-details-dialog analytics-card" role="dialog" aria-modal="true" aria-label={`Все данные: ${title}`} onClick={event => event.stopPropagation()}>
          <header><div><h2>{title}</h2>{subtitle && <small>{subtitle}</small>}</div><button type="button" className="analytics-details-close" onClick={() => setDetails(false)} aria-label="Закрыть">×</button></header>
          <div className="analytics-details-content"><AnalyticsFullView.Provider value={true}>{typeof children === 'function' ? children(tooltip, true) : children}</AnalyticsFullView.Provider></div>
        </section>
      </div>}
    </section>
  );
}

function Donut({ rows, tooltip, unit = 'заявок' }) {
  const full = useContext(AnalyticsFullView);
  const shown = full ? rows.filter(row => row.value > 0) : foldTail(rows);
  const total = shown.reduce((sum, row) => sum + row.value, 0);
  const classes = colorClass(shown);
  const [active, setActive] = useState(null);
  if (!total) return <p className="analytics-empty">Нет данных за выбранный период</p>;
  const radius = 76;
  const width = 30;
  const circumference = 2 * Math.PI * radius;
  // A 2px surface gap separates neighbouring slices.
  const gap = shown.length > 1 ? 2 : 0;
  let offset = 0;
  return (
    <div className="analytics-donut">
      <svg viewBox="0 0 200 200" role="img" aria-label={shown.map(row => `${row.label}: ${row.value}`).join(', ')}>
        <g transform="rotate(-90 100 100)">
          {shown.map((row, index) => {
            const length = (row.value / total) * circumference;
            const dash = Math.max(length - gap, 0.5);
            const segment = (
              <circle
                key={row.label}
                cx="100" cy="100" r={radius}
                className={`donut-slice ${classes[index]} ${active === index ? 'active' : ''}`}
                strokeWidth={active === index ? width + 6 : width}
                strokeDasharray={`${dash} ${circumference - dash}`}
                strokeDashoffset={-offset}
                onMouseMove={event => { setActive(index); tooltip.show(event, `${row.label}: ${formatNumber(row.value)} ${unit} (${Math.round((row.value / total) * 100)}%)`); }}
                onMouseLeave={() => { setActive(null); tooltip.hide(); }}
              >
                <title>{`${row.label}: ${row.value}`}</title>
              </circle>
            );
            offset += length;
            return segment;
          })}
        </g>
        <text x="100" y="96" textAnchor="middle" className="donut-total">{formatNumber(total)}</text>
        <text x="100" y="118" textAnchor="middle" className="donut-caption">всего</text>
      </svg>
    </div>
  );
}

function Legend({ rows, total = true }) {
  const full = useContext(AnalyticsFullView);
  const shown = full ? rows.filter(row => row.value > 0) : foldTail(rows);
  const classes = colorClass(shown);
  const sum = rows.reduce((acc, row) => acc + row.value, 0);
  return (
    <table className="analytics-table analytics-legend">
      <tbody>
        {shown.map((row, index) => (
          <tr key={row.label}>
            <td><i className={`swatch ${classes[index]}`} />{row.label}</td>
            <td>{formatNumber(row.value)}</td>
          </tr>
        ))}
        {total && <tr className="total"><td>Всего</td><td>{formatNumber(sum)}</td></tr>}
      </tbody>
    </table>
  );
}

function HorizontalBars({ rows, tooltip, unit = 'заявок', format = formatNumber, includeZero = false }) {
  const full = useContext(AnalyticsFullView);
  const eligible = includeZero ? rows : rows.filter(row => row.value > 0);
  const visible = full ? eligible : eligible.slice(0, 10);
  if (!visible.length) return <p className="analytics-empty">Нет данных за выбранный период</p>;
  const max = Math.max(...visible.map(row => row.value));
  return (
    <div className="analytics-hbars">
      {visible.map(row => (
        <div
          className="hbar-row"
          key={row.label}
          onMouseMove={event => tooltip.show(event, `${row.label}: ${format(row.value)} ${unit}`)}
          onMouseLeave={tooltip.hide}
        >
          <span className="hbar-label" title={row.label}>{row.label}</span>
          <span className="hbar-track"><span className="hbar-fill" style={{ width: `${row.value > 0 ? Math.max((row.value / max) * 100, 1.5) : 0}%` }} /></span>
          <b>{format(row.value)}</b>
        </div>
      ))}
    </div>
  );
}

function DailyColumns({ rows, tooltip }) {
  const max = Math.max(1, ...rows.map(row => row.value));
  const total = rows.reduce((sum, row) => sum + row.value, 0);
  if (!total) return <p className="analytics-empty">За период новых заявок не было</p>;
  const ticks = [...new Set([0, Math.ceil(max / 2), max])];
  const labelEvery = Math.max(1, Math.ceil(rows.length / 10));
  return (
    <div className="analytics-columns">
      <div className="columns-axis">{[...ticks].reverse().map(tick => <span key={tick}>{tick}</span>)}</div>
      <div className="columns-plot">
        {ticks.map(tick => <i className="columns-grid" style={{ bottom: `${(tick / max) * 100}%` }} key={tick} />)}
        {rows.map((row, index) => (
          <div
            className="column"
            key={row.date}
            onMouseMove={event => tooltip.show(event, `${formatDate(row.date)}: ${formatNumber(row.value)} заявок`)}
            onMouseLeave={tooltip.hide}
          >
            <span className="column-fill" style={{ height: `${(row.value / max) * 100}%` }} />
            {index % labelEvery === 0 && <small>{formatShortDate(row.date)}</small>}
          </div>
        ))}
      </div>
    </div>
  );
}

const WEEKDAY_LABELS = ['Пн','Вт','Ср','Чт','Пт','Сб','Вс'];
const heatValue = value => value > 0 && value < .01 ? '<0,01' : Number(value).toLocaleString('ru-RU', {maximumFractionDigits:2});

function HeatmapHelp() {
  const ref=useRef(null);
  useEffect(()=>{
    const outside=event=>{if(ref.current?.open&&!ref.current.contains(event.target))ref.current.open=false};
    const escape=event=>{if(event.key==='Escape'&&ref.current?.open){event.preventDefault();event.stopPropagation();ref.current.open=false;ref.current.querySelector('summary')?.focus()}};
    document.addEventListener('pointerdown',outside);
    document.addEventListener('keydown',escape);
    return()=>{document.removeEventListener('pointerdown',outside);document.removeEventListener('keydown',escape)};
  },[]);
  return <details className="analytics-help" ref={ref}><summary aria-label="Что означают числа на тепловой карте?"><HelpCircle/></summary><div className="heatmap-explanation"><p><b>Что означают числа?</b> Это средняя занятость аудиторий за час для данного дня недели в выбранном периоде.</p><p>Например, <b>1</b> — занятость, эквивалентная одной аудитории на весь час; <b>0,5</b> — половине часа одной аудитории; <b>2</b> — двум аудиториям на весь час. Эта занятость может складываться из нескольких помещений и частей часа. Число в скобках рядом с днём показывает, сколько таких дней вошло в период.</p><p>Учтены подтверждённые и состоявшиеся брони, включая дополнительные аудитории. Это не процент загрузки. Наведите на ячейку, чтобы увидеть суммарные часы и число броней.</p></div></details>
}

function OccupancyHeatmap({data}) {
  if(!data?.rows?.length||!data.hours?.length)return <p className="analytics-empty">Нет данных для тепловой карты</p>;
  const max=Math.max(0,...data.rows.flatMap(row=>row.cells.map(cell=>cell.average_rooms||0)));
  return <div className="occupancy-heatmap">
    <div className="heatmap-scroll" tabIndex={0} role="region" aria-label="Тепловая карта: прокрутите по горизонтали для просмотра всех часов">
      <table className="heatmap-table"><thead><tr><th scope="col">День</th>{data.hours.map(hour=><th scope="col" key={hour}>{String(hour).padStart(2,'0')}:00</th>)}</tr></thead><tbody>{data.rows.map(row=><tr key={row.weekday}><th scope="row">{WEEKDAY_LABELS[row.weekday]} <small>({row.occurrences})</small></th>{row.cells.map(cell=>{const value=cell.average_rooms;const level=value===null?'none':value<=0?'0':Math.max(1,Math.min(4,Math.ceil(value/max*4)));const label=value===null?'Этот день недели отсутствует в периоде':`${WEEKDAY_LABELS[row.weekday]}, ${String(cell.hour).padStart(2,'0')}:00–${String(cell.hour+1).padStart(2,'0')}:00: в среднем ${heatValue(value)} ауд.; суммарно ${heatValue(cell.booked_minutes/60)} ч, пересечений с бронями: ${cell.booking_count}; таких дней: ${row.occurrences}`;return <td key={cell.hour} className={`heatmap-cell level-${level}`} title={label} aria-label={label} tabIndex={0}>{value===null?'—':heatValue(value)}</td>})}</tr>)}</tbody></table>
    </div>
    <div className="heatmap-legend"><span>Меньше броней</span>{[0,1,2,3,4].map(level=><i key={level} className={`heatmap-swatch level-${level}`}/>)}<span>Больше броней</span><small>Чем темнее зелёный, тем больше средняя занятость относительно других часов в выбранном периоде.</small></div>
    {!max&&<p className="analytics-empty">За выбранный период подтверждённых и состоявшихся броней нет.</p>}
  </div>
}

function ReasonsChart({data,tooltip}) {
  const groups=[['Отмены',data?.cancellations||[]],['Отказы',data?.rejections||[]]];
  return <div className="analytics-reasons">{groups.map(([label,rows])=><section key={label}><h3>{label}</h3>{rows.length?<HorizontalBars rows={rows} tooltip={tooltip} unit="заявок"/>:<p className="analytics-empty">За период нет данных</p>}</section>)}</div>
}

function CohortTrend({data}) {
  if(!data?.rows?.length)return <p className="analytics-empty">Нет данных за выбранный период</p>;
  const max=Math.max(1,...data.rows.map(row=>row.new));
  const label=row=>{const day=new Date(`${row.date}T00:00:00`);return data.interval==='month'?day.toLocaleDateString('ru-RU',{month:'short',year:'2-digit'}):`с ${formatShortDate(row.date)}`};
  return <><div className="cohort-legend"><span className="cohort-new">Новые</span><span className="cohort-confirmed">Подтверждены / состоялись</span><span className="cohort-cancelled">Отменены</span></div><div className="cohort-scroll" tabIndex={0} role="region" aria-label="Динамика заявок по периодам"><div className="cohort-chart">{data.rows.map(row=><div className="cohort-period" key={row.date} title={`${label(row)}: новых ${row.new}, подтверждены или состоялись ${row.confirmed}, отменены ${row.cancelled}`}><div className="cohort-bars">{[['new','Новые'],['confirmed','Подтверждены'],['cancelled','Отменены']].map(([key,name])=><div className="cohort-column" key={key} aria-label={`${name}: ${row[key]}`}><b>{row[key]}</b><i className={`cohort-${key}`} style={{height:`${row[key]/max*150}px`}}/></div>)}</div><small>{label(row)}</small></div>)}</div></div><p className="analytics-note">Заявки сгруппированы по дате создания; подтверждение и отмена показаны по текущему статусу, а не по дате решения. Серия и комплект считаются одной заявкой.</p></>
}

function RoomRanking({data}) {
  const [mode,setMode]=useState('most');
  const full=useContext(AnalyticsFullView);
  const allRows=data?.[mode]||[];
  const rows=full?allRows:allRows.slice(0,10);
  return <><div className="ranking-switch"><button type="button" className={mode==='most'?'active':''} aria-pressed={mode==='most'} onClick={()=>setMode('most')}>Самые востребованные</button><button type="button" className={mode==='least'?'active':''} aria-pressed={mode==='least'} onClick={()=>setMode('least')}>Наименее востребованные</button></div>{rows.length?<div className="analytics-scroll"><table className="analytics-table ranking-table"><thead><tr><th>Аудитория и корпус</th><th>Броней</th><th>Часов</th></tr></thead><tbody>{rows.map(row=><tr key={row.id}><td><b>Ауд. {row.number}</b><small>{row.building}</small></td><td>{formatNumber(row.bookings)}</td><td>{formatNumber(row.hours)}</td></tr>)}</tbody></table></div>:<p className="analytics-empty">Нет аудиторий</p>}<p className="analytics-note">Подтверждённые и состоявшиеся брони по дате мероприятия; дополнительные аудитории считаются отдельно. В нижнем рейтинге — активные аудитории, включая те, где броней не было.</p></>
}

function Change({ value }) {
  if (value === null || value === undefined) return <small className="kpi-change">нет данных за прошлый период</small>;
  const sign = value > 0 ? '+' : value < 0 ? '−' : '';
  return <small className={`kpi-change ${value > 0 ? 'up' : value < 0 ? 'down' : ''}`}>{sign}{formatNumber(Math.abs(value))}% к прошлому периоду</small>;
}

export default function AnalyticsPage({ request, notice }) {
  const [preset, setPreset] = useState('30');
  const [range, setRange] = useState(() => presetRange('30'));
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const reportRef = useRef(null);

  const load = async ([from, to] = range) => {
    if (!from || !to) return;
    setLoading(true);
    try {
      setData(await request(`/api/admin/analytics?date_from=${from}&date_to=${to}`));
    } catch (error) {
      notice(error.message);
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { load(); }, []);

  const choosePreset = key => {
    setPreset(key);
    const next = presetRange(key);
    setRange(next);
    load(next);
  };
  const changeDate = (index, value) => {
    setPreset('custom');
    setRange(current => (index ? [current[0], value] : [value, current[1]]));
  };

  const periodLabel = data ? `${formatDate(data.period.from)} — ${formatDate(data.period.to)}` : '';
  const responsibleRows = useMemo(() => (data?.responsible || []).map(row => ({ label: row.label, value: row.new })), [data]);

  const exportHtml = () => {
    if (!reportRef.current || !data) return;
    const clone = reportRef.current.cloneNode(true);
    clone.querySelectorAll('.no-export, .analytics-tooltip').forEach(node => node.remove());
    clone.querySelectorAll('.analytics-card.collapsed').forEach(node => node.classList.remove('collapsed'));
    const html = `<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">`
      + `<title>Аналитика заявок · ${periodLabel}</title><style>${analyticsCss}</style></head>`
      + `<body class="analytics-export">${clone.outerHTML}</body></html>`;
    const link = document.createElement('a');
    link.href = URL.createObjectURL(new Blob([html], { type: 'text/html;charset=utf-8' }));
    link.download = `analytics_${data.period.from}_${data.period.to}.html`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(link.href), 1000);
  };

  return (
    <section className="content-page analytics-page" ref={reportRef}>
      <div className="page-heading analytics-heading">
        <div>
          <small>ОТЧЁТ АДМИНИСТРАТОРА</small>
          <h1>Аналитика заявок</h1>
          <p>{data ? <>Период: <b>{periodLabel}</b> · сформирован {new Date(data.generated_at).toLocaleString('ru-RU', { hour12: false, day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' })}</> : 'Выберите период отчёта'}</p>
        </div>
        <div className="analytics-actions no-export">
          <button type="button" className="secondary" disabled={!data} onClick={() => window.print()}><Printer />Печать / PDF</button>
          <button type="button" className="primary" disabled={!data} onClick={exportHtml}><Download />Скачать отчёт</button>
        </div>
      </div>

      <div className="analytics-filters no-export">
        <div className="analytics-presets">
          {PRESETS.map(([key, label]) => (
            <button type="button" className={preset === key ? 'active' : ''} onClick={() => choosePreset(key)} key={key}>{label}</button>
          ))}
        </div>
        <div className="analytics-range">
          <label><span>С</span><input type="date" value={range[0]} max={range[1]} onChange={event => changeDate(0, event.target.value)} /></label>
          <label><span>По</span><input type="date" value={range[1]} min={range[0]} onChange={event => changeDate(1, event.target.value)} /></label>
          <button type="button" className="primary" disabled={loading} onClick={() => load()}><RefreshCw />{loading ? 'Считаем…' : 'Сформировать'}</button>
        </div>
      </div>

      {!data ? (
        <div className="analytics-empty-state"><BarChart3 /><b>{loading ? 'Собираем данные…' : 'Нет данных'}</b></div>
      ) : (
        <>
          <div className="analytics-kpis">
            <article><span>Текущие</span><b>{formatNumber(data.kpi.current)}</b><small>Сейчас в работе: на согласовании и предстоящие</small></article>
            <article><span>Новые</span><b>{formatNumber(data.kpi.new)}</b><Change value={data.kpi.new_change} /></article>
            <article><span>Завершённые</span><b>{formatNumber(data.kpi.completed)}</b><Change value={data.kpi.completed_change} /></article>
            <article><span>Бронирований в новых заявках</span><b>{formatNumber(data.kpi.records_new)}</b><small>С учётом всех дат серий</small></article>
          </div>

          <div className="analytics-grid">
            <div className="analytics-row analytics-row--overview">
            <Card title="Ответственное лицо" subtitle="Диаграмма — новые заявки за период; в таблице текущие — на сегодня">
              {(tooltip, full) => (
                <>
                  <Donut rows={responsibleRows} tooltip={tooltip} />
                  <div className="analytics-scroll">
                    <table className="analytics-table">
                      <thead><tr><th>Ответственный</th><th>Текущие</th><th>Новые</th><th>Завершённые</th></tr></thead>
                      <tbody>
                        {(full ? data.responsible : data.responsible.slice(0, 10)).map((row, index) => {
                          const classes = colorClass(foldTail(responsibleRows));
                          const position = foldTail(responsibleRows).findIndex(item => item.label === row.label);
                          return (
                            <tr key={row.label}>
                              <td><i className={`swatch ${position >= 0 ? classes[position] : 'slot-other'}`} />{row.label}</td>
                              <td>{row.current}</td><td>{row.new}</td><td>{row.completed}</td>
                            </tr>
                          );
                        })}
                        <tr className="total"><td>Всего</td>
                          <td>{data.responsible.reduce((sum, row) => sum + row.current, 0)}</td>
                          <td>{data.responsible.reduce((sum, row) => sum + row.new, 0)}</td>
                          <td>{data.responsible.reduce((sum, row) => sum + row.completed, 0)}</td>
                        </tr>
                      </tbody>
                    </table>
                  </div>
                </>
              )}
            </Card>

            <Card title="Подразделения" subtitle="Новые заявки за период · топ 10">
              {tooltip => <HorizontalBars rows={data.departments} tooltip={tooltip} />}
            </Card>

            <Card title="Где планируется проведение мероприятия?" subtitle="Корпуса · новые заявки за период">
              {tooltip => <><Donut rows={data.buildings} tooltip={tooltip} /><Legend rows={data.buildings} /></>}
            </Card>
            </div>
            <div className="analytics-row analytics-row--operational">
            <Card title="Рейтинг аудиторий" subtitle="Топ-10 по часам бронирования">
              {() => <RoomRanking data={data.room_statistics}/>}
            </Card>
            <div className="analytics-stack">
            <Card title="По этапам" subtitle="Сейчас">
              {(tooltip, full) => (
                <table className="analytics-table">
                  <tbody>
                    {(full ? data.stages_now : data.stages_now.slice(0, 10)).map((row, index) => <tr key={row.label}><td>{index + 1}&nbsp;&nbsp;{row.label}</td><td>{formatNumber(row.value)}</td></tr>)}
                    <tr className="total"><td>Всего</td><td>{formatNumber(data.stages_now.reduce((sum, row) => sum + row.value, 0))}</td></tr>
                  </tbody>
                </table>
              )}
            </Card>

            <Card title="Время прохождения по этапам" subtitle="Новые заявки за период">
              {(tooltip, full) => (
                <table className="analytics-table">
                  <thead><tr><th>Этап</th><th>Заявок</th><th>Медиана</th><th>Макс.</th></tr></thead>
                  <tbody>
                    {(full ? data.stage_times : data.stage_times.slice(0, 10)).map(row => (
                      <tr key={row.label}><td>{row.label}</td><td>{row.count}</td><td>{formatDuration(row.median_minutes)}</td><td>{formatDuration(row.max_minutes)}</td></tr>
                    ))}
                  </tbody>
                </table>
              )}
            </Card>
            </div>
            <div className="analytics-stack">
            <Card title="Сравнение корпусов" subtitle="Часы подтверждённых и состоявшихся броней за период">
              {tooltip => <><HorizontalBars rows={data.room_statistics?.buildings||[]} tooltip={tooltip} unit="ч" includeZero /><p className="analytics-note">Часы всех аудиторий, включая дополнительные. Это не процент загрузки.</p></>}
            </Card>

            <Card title="Причины отмен и отказов" subtitle="По дате решения или отмены">
              {tooltip => <ReasonsChart data={data.reasons} tooltip={tooltip}/>}
            </Card>
            </div>
            </div>
            <div className="analytics-row analytics-row--summary">
            <Card title="Требуется аудитория для организации питания?" subtitle="Новые заявки за период">
              {tooltip => <><Donut rows={data.catering} tooltip={tooltip} /><Legend rows={data.catering} /></>}
            </Card>

            <Card title="Заявка на материально-техническое обеспечение" subtitle="Новые заявки за период">
              {tooltip => (
                <>
                  <Donut rows={data.equipment} tooltip={tooltip} />
                  <Legend rows={data.equipment} />
                  {data.equipment_items.length > 0 && <><h3>Что запрашивали</h3><HorizontalBars rows={data.equipment_items} tooltip={tooltip} unit="раз" /></>}
                </>
              )}
            </Card>

            <Card title="Итоги заявок" subtitle="Текущий статус новых заявок за период">
              {tooltip => <><Donut rows={data.outcomes} tooltip={tooltip} /><Legend rows={data.outcomes} /></>}
            </Card>
            </div>
            <Card title="Динамика заявок" subtitle={data.cohort_trend?.interval==='month'?'По месяцам создания':'По дням создания'} wide>
              {() => <CohortTrend data={data.cohort_trend}/>}
            </Card>

            <Card title="Тепловая карта загрузки аудиторий" subtitle="Дни недели и рабочие часы · среднее за период" help={<HeatmapHelp/>} wide>
              {() => <OccupancyHeatmap data={data.occupancy_heatmap} />}
            </Card>

            <Card title="Динамика новых заявок" subtitle="По дням поступления" wide>
              {tooltip => <DailyColumns rows={data.daily_new} tooltip={tooltip} />}
            </Card>
          </div>
        </>
      )}
    </section>
  );
}
