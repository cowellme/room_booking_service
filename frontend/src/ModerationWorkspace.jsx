import {useEffect,useMemo,useRef,useState} from 'react';
import {Archive,CalendarRange,ChevronDown,ChevronRight,Eye,Folder,FolderInput,GripVertical,Hash,Pencil,Pin,Plus,RotateCcw,Search,Star,Trash2,WandSparkles,X} from 'lucide-react';
import './moderationWorkspace.css';

const blank={version:0,folders:[],entries:{},tag_catalog:[],tag_colors:{}};
const noPending=[];
const months=['Январь','Февраль','Март','Апрель','Май','Июнь','Июль','Август','Сентябрь','Октябрь','Ноябрь','Декабрь'];
const legacyTags=new Map([['important','Важно'],['long','Длительная программа'],...months.map((name,i)=>[`month-${String(i+1).padStart(2,'0')}`,name])])
const tagKey=value=>value.trim().toLocaleLowerCase('ru');
const tagColors=['slate','blue','rose','mint','purple','peach','yellow'];
const defaultTagColor=value=>tagColors[Array.from(tagKey(value)).reduce((n,c)=>(n*31+c.codePointAt(0))%tagColors.length,0)];
const uniqueTags=values=>[...new Map(values.map(value=>[tagKey(value),value])).values()];
function restoreTags(data){
  const sourceEntries=data.entries||{};
  const entries=Object.fromEntries(Object.entries(sourceEntries).map(([key,entry])=>[key,{...entry,favorite:Boolean(entry.favorite),tags:uniqueTags((entry.tags||[]).map(tag=>legacyTags.get(tag)||tag))}]));
  const catalog=data.tag_catalog||uniqueTags(Object.values(entries).flatMap(entry=>entry.tags));
  return {...data,folders:data.folders||[],entries,tag_catalog:catalog,tag_colors:data.tag_colors||{}};
}
const emptyEntry={folder:null,tags:[],working:false,favorite:false};
const Tag=({value,color})=><span className="mw-tag" data-color={color||defaultTagColor(value)}>{value}</span>;
function TagPicker({selected,catalog,colors,disabled,onChange,onColorChange,onDelete}){
  const [query,setQuery]=useState('');
  const input=query.trim();
  const items=catalog.filter(tag=>tagKey(tag).includes(tagKey(input)));
  const exists=catalog.some(tag=>tagKey(tag)===tagKey(input));
  const add=tag=>{if(!disabled&&selected.length<40&&(catalog.includes(tag)||catalog.length<300)){onChange([...selected,tag]);setQuery('')}};
  return <div className="mw-tag-picker">
    <label className="mw-tag-search">Теги <input value={query} onChange={e=>setQuery(e.target.value)} maxLength={48} placeholder="Найти или создать тег" disabled={disabled} onKeyDown={e=>{if(e.key==='Enter'&&input&&!exists){e.preventDefault();add(input)}}}/></label>
    {selected.length>0&&<><small>Выбраны</small><div className="mw-tag-selected">{selected.map(tag=><div className="mw-tag-color-row" key={tag}><button type="button" disabled={disabled} aria-label={`Снять тег «${tag}»`} onClick={()=>onChange(selected.filter(item=>item!==tag))}><Tag value={tag} color={colors[tag]}/> ×</button><span>{tagColors.map(color=><button type="button" className={colors[tag]===color?'active':''} data-color={color} title={`Цвет тега «${tag}»`} aria-label={`Назначить цвет ${color}`} onClick={()=>onColorChange(tag,color)} key={color}/>)}</span></div>)}</div></>}
    <small>Существующие теги</small>
    <div className="mw-tag-options">{items.map(tag=><span className="mw-tag-option" key={tag}><button type="button" disabled={disabled||selected.length>=40} onClick={()=>selected.includes(tag)?onChange(selected.filter(item=>item!==tag)):add(tag)}><Tag value={tag} color={colors[tag]}/></button><button type="button" className="mw-tag-delete" disabled={disabled} title={`Удалить тег «${tag}»`} aria-label={`Удалить тег «${tag}»`} onClick={()=>onDelete(tag)}><X size={13}/></button></span>)}
      {!items.length&&<span>Нет подходящих меток</span>}
    </div>
    {input&&!exists&&<button type="button" disabled={disabled||selected.length>=40||catalog.length>=300} onClick={()=>add(input)}>＋ Создать «{input}»</button>}
  </div>;
}
const keyOf=item=>item.series_id?'series:'+item.series_id:'item:'+(item.parent_booking_id||item.id);
const ISO_DAY=86400000;
const PAGE_SIZE=40;
const stamp=date=>Date.parse(date+'T00:00:00Z');
const dateLabel=date=>!date?'—':date.length===10?date.split('-').reverse().join('.'):new Intl.DateTimeFormat('ru-RU',{timeZone:'Europe/Moscow'}).format(new Date(date));
const today=()=>new Intl.DateTimeFormat('sv-SE',{timeZone:'Europe/Moscow'}).format(new Date());

function inPeriod(date,period){
  if(period==='all')return true;
  const current=today();
  if(period==='year')return date.slice(0,4)===current.slice(0,4);
  if(period==='month')return date.slice(0,7)===current.slice(0,7);
  const now=stamp(current);
  const monday=now-((new Date(now).getUTCDay()+6)%7)*ISO_DAY;
  return stamp(date)>=monday&&stamp(date)<monday+7*ISO_DAY;
}

function buildGroups(items){
  const groups=new Map();
  for(const row of items){
    if(row.record_kind&&row.record_kind!=='booking')continue;
    const key=keyOf(row);
    const group=groups.get(key)||[];
    group.push(row);groups.set(key,group);
  }
  return [...groups].map(([key,entries])=>{
    entries.sort((a,b)=>a.date.localeCompare(b.date)||Number(Boolean(a.parent_booking_id))-Number(Boolean(b.parent_booking_id))||a.id-b.id);
    const row=entries.find(entry=>!entry.parent_booking_id)||entries[0];
    const start=entries[0].date,end=entries.at(-1).date;
    const submitted=entries.map(entry=>entry.created_at).filter(Boolean).sort()[0];
    return {key,row,start,end,submitted,shortNotice:entries.some(entry=>entry.short_notice),long:(stamp(end)-stamp(start))/ISO_DAY+1>=30,
      pending:entries.some(entry=>entry.status==='pending'),
      inProgress:entries.some(entry=>entry.status==='in_progress'),
      approved:entries.some(entry=>['approved','completed','no_show'].includes(entry.status)),
      rejected:entries.some(entry=>entry.status==='rejected')};
  }).sort((a,b)=>String(b.submitted||'').localeCompare(String(a.submitted||''))||b.row.id-a.row.id);
}

export default function ModerationWorkspace({pending=noPending,reviewable=noPending,records,active:pageActive=true,request,notice,focusId,openReview,openBooking,takeInWork,approveRequest,rejectRequest,actionsBusy=false,archiveBooking,replaceBooking,deleteBooking}){
  const bookingMode=records!==undefined;
  const workspaceScope=bookingMode?'bookings':'moderation';
  const [settings,setSettings]=useState(null);
  const [folder,setFolder]=useState('all'),[period,setPeriod]=useState('all'),[query,setQuery]=useState('');
  const emptyFilters={responsible:'',title:'',reference:'',room:'',building:'',department:'',eventFormat:'',dateFrom:'',dateTo:''};
  const [filters,setFilters]=useState(emptyFilters);
  const [name,setName]=useState(''),[editing,setEditing]=useState(null),[failure,setFailure]=useState('');
  const [creatingFolder,setCreatingFolder]=useState(null),[context,setContext]=useState(null),[contextPanel,setContextPanel]=useState(null);
  const [dragging,setDragging]=useState(null),[dropFolder,setDropFolder]=useState(null);
  const [folderDragging,setFolderDragging]=useState(null),[folderDrop,setFolderDrop]=useState(null);
  const [sidebarWidth,setSidebarWidth]=useState(()=>Math.max(220,Math.min(520,Number(localStorage.getItem('booking-folder-width'))||260)));
  const [saving,setSaving]=useState(false),[reload,setReload]=useState(0);
  const [page,setPage]=useState(1);
  const savingRef=useRef(false);
  const pendingSignature=pending.map(item=>item.id).join(',');
  const resizeSidebar=event=>{event.preventDefault();const startX=event.clientX,startWidth=sidebarWidth;const move=moveEvent=>setSidebarWidth(Math.max(220,Math.min(520,startWidth+moveEvent.clientX-startX)));const stop=()=>{document.removeEventListener('pointermove',move);document.removeEventListener('pointerup',stop);document.body.classList.remove('mw-is-resizing')};document.body.classList.add('mw-is-resizing');document.addEventListener('pointermove',move);document.addEventListener('pointerup',stop)};
  useEffect(()=>{localStorage.setItem('booking-folder-width',String(sidebarWidth))},[sidebarWidth]);
  useEffect(()=>{if(!context)return;const close=event=>{if(!event.target.closest?.('.mw-context-menu,.mw-context-submenu')){setContext(null);setContextPanel(null)}};const escape=event=>{if(event.key==='Escape'){setContext(null);setContextPanel(null)}};document.addEventListener('pointerdown',close);document.addEventListener('keydown',escape);return()=>{document.removeEventListener('pointerdown',close);document.removeEventListener('keydown',escape)}},[context]);
  useEffect(()=>{
    if(!pageActive)return;
    let active=true;
    request(`/api/admin/moderation-workspace?scope=${workspaceScope}`).then(data=>{if(active)setSettings(restoreTags(data))}).catch(e=>{if(active)setFailure(e.message)});
    return ()=>{active=false};
  },[request,reload,pageActive,workspaceScope]);
  const pendingKeys=new Map(reviewable.map(item=>[keyOf(item),item]));
  const allGroups=useMemo(()=>buildGroups((records||pending).filter(item=>!bookingMode||!['pending','in_progress'].includes(item.status))),[pendingSignature,records,bookingMode]);
  const model=settings||blank;
  const normalized=value=>String(value||'').trim().toLocaleLowerCase('ru-RU');
  const sourceRows=records||pending;
  const optionValues=key=>[...new Set(sourceRows.map(item=>item[key]).filter(Boolean))].sort((a,b)=>String(a).localeCompare(String(b),'ru'));
  const buildingOptions=optionValues('building'),departmentOptions=optionValues('department_name'),eventFormatOptions=optionValues('event_format');
  const filterCount=Object.values(filters).filter(value=>String(value).trim()).length;
  const groups=allGroups.filter(group=>{const item=group.row;return (!filters.responsible||normalized(`${item.customer_name||''} ${item.booked_by||''} ${item.owner_name||''}`).includes(normalized(filters.responsible)))&&(!filters.title||normalized(item.title).includes(normalized(filters.title)))&&(!filters.reference||normalized(item.external_reference).includes(normalized(filters.reference)))&&(!filters.room||normalized(item.room_number).includes(normalized(filters.room)))&&(!filters.building||item.building===filters.building)&&(!filters.department||item.department_name===filters.department)&&(!filters.eventFormat||item.event_format===filters.eventFormat)&&(!filters.dateFrom||group.start>=filters.dateFrom)&&(!filters.dateTo||group.end<=filters.dateTo)});
  const updateFilter=(key,value)=>setFilters(current=>({...current,[key]:value}));
  const browse=key=>{setFolder(key);setPeriod('all');setPage(1);setEditing(null);setContext(null);setContextPanel(null)};
  const save=async next=>{
    if(!settings||savingRef.current)return false;
    savingRef.current=true;setSaving(true);setFailure('');
    try{
      const saved=await request(`/api/admin/moderation-workspace?scope=${workspaceScope}`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(next)});
      setSettings(saved);return true;
    }catch(e){setFailure(e.message);return false}
    finally{savingRef.current=false;setSaving(false)}
  };
  const deleteTag=tag=>{const entries=Object.fromEntries(Object.entries(model.entries).map(([key,value])=>[key,{...value,tags:(value.tags||[]).filter(item=>item!==tag)}]));const tag_colors={...model.tag_colors};delete tag_colors[tag];return save({...model,entries,tag_catalog:model.tag_catalog.filter(item=>item!==tag),tag_colors})};
  const updateEntry=(key,change)=>{
    const value={...(model.entries[key]||emptyEntry),...change};
    const entries={...model.entries,[key]:value};
    if(!value.folder&&!value.tags.length&&!value.working&&!value.favorite)delete entries[key];
    const tag_catalog=change.tags?uniqueTags([...model.tag_catalog,...change.tags]):model.tag_catalog;
    return save({...model,entries,tag_catalog});
  };
  const addFolder=async event=>{
    event.preventDefault();
    const label=name.trim();
    if(!label)return;
    if(model.folders.some(item=>item.name.toLocaleLowerCase('ru')===label.toLocaleLowerCase('ru'))){notice('Папка с таким названием уже есть');return}
    const id='folder-'+Date.now().toString(36)+'-'+Math.random().toString(36).slice(2,9);
    const parent_id=creatingFolder?.parentId||null;
    if(await save({...model,folders:[...model.folders,{id,name:label,parent_id}]})){setName('');setCreatingFolder(null);browse(id)}
  };
  const remove=async item=>{
    if(!window.confirm(`Удалить папку «${item.name}»? Заявки сохранятся, а вложенные папки поднимутся на уровень выше.`))return;
    const entries=Object.fromEntries(Object.entries(model.entries).map(([key,value])=>[key,value.folder===item.id?{...value,folder:null}:value]));
    const folders=model.folders.filter(x=>x.id!==item.id).map(x=>x.parent_id===item.id?{...x,parent_id:item.parent_id||null}:x);
    if(await save({...model,folders,entries})&&folder===item.id)browse('all');
  };
  const patchFolder=(id,change)=>save({...model,folders:model.folders.map(item=>item.id===id?{...item,...change}:item)});
  const renameFolder=async(event,item)=>{event.preventDefault();const next=name.trim();if(!next){setFailure('Введите название папки');return}if(next===item.name){setEditing(null);setName('');return}if(await patchFolder(item.id,{name:next})){setEditing(null);setName('')}};
  const moveFolder=(sourceId,targetId)=>{
    if(sourceId===targetId)return;
    const source=model.folders.find(item=>item.id===sourceId),target=model.folders.find(item=>item.id===targetId);
    if(!source||!target||(source.parent_id||null)!==(target.parent_id||null))return;
    const folders=model.folders.filter(item=>item.id!==sourceId),targetIndex=folders.findIndex(item=>item.id===targetId);
    folders.splice(targetIndex,0,{...source,pinned:Boolean(target.pinned)});save({...model,folders});
  };
  const focused=focusId&&((records||pending).find(item=>item.id===focusId));
  const focusKey=focused&&keyOf(focused);
  useEffect(()=>{
    if(!focusId)return;
    setFolder('all');setPeriod('all');setQuery('');
  },[focusId]);
  useEffect(()=>{
    if(!focusKey)return;
    const timer=setTimeout(()=>document.getElementById('review-'+focusKey)?.scrollIntoView({block:'nearest'}),100);
    return ()=>clearTimeout(timer);
  },[focusKey]);
  const matchesFolder=group=>{
    const assigned=model.entries[group.key]?.folder;
    if(folder==='all')return true;
    if(folder==='favorites')return Boolean(model.entries[group.key]?.favorite);
    if(folder==='booking-working')return group.pending;
    if(folder==='booking-confirmed')return group.approved&&!group.pending;
    if(folder==='inbox')return group.pending;
    if(folder==='in-progress')return group.inProgress;
    if(folder==='confirmed')return group.approved&&!group.pending;
    if(folder==='long')return group.long;
    if(folder.startsWith('date:'))return !assigned&&group.start.startsWith(folder.slice(5));
    return assigned===folder;
  };
  const needle=query.trim().toLocaleLowerCase('ru');
  const rows=groups.filter(group=>matchesFolder(group)&&inPeriod(group.start,period)&&
    (!needle||[group.row.title,group.row.customer_name,group.row.booked_by,group.row.external_reference].some(value=>value?.toLocaleLowerCase('ru').includes(needle))));
  const pageCount=Math.max(1,Math.ceil(rows.length/PAGE_SIZE));
  const currentPage=Math.min(page,pageCount);
  const pageRows=rows.slice((currentPage-1)*PAGE_SIZE,currentPage*PAGE_SIZE);
  useEffect(()=>{setPage(1)},[folder,period,query]);
  useEffect(()=>{setPage(value=>Math.min(value,Math.max(1,Math.ceil(rows.length/PAGE_SIZE))))},[rows.length]);
  const groupLabel=folder==='inbox'?'Поступившие заявки':folder==='in-progress'?'Принятые в работу':folder==='confirmed'?'Подтверждённые':folder==='booking-working'?'В работе':folder==='booking-confirmed'?'Подтверждённые':folder==='long'?'Длительные программы':folder==='favorites'?'Избранное':folder==='all'?(bookingMode?'Все бронирования':'Все заявки'):model.folders.find(x=>x.id===folder)?.name||
    (folder.length===9?folder.slice(5):`${months[Number(folder.slice(-2))-1]} ${folder.slice(5,9)}`);
  const dropProps=(id)=>({
    onDragOver:event=>{if(!dragging||saving)return;event.preventDefault();event.dataTransfer.dropEffect='move';setDropFolder(id)},
    onDragLeave:event=>{if(!(event.relatedTarget instanceof Node)||!event.currentTarget.contains(event.relatedTarget))setDropFolder(null)},
    onDrop:async event=>{event.preventDefault();const key=dragging;setDragging(null);setDropFolder(null);if(!key||saving)return;
      const destination=id==='auto'?null:id;
      if(await updateEntry(key,{folder:destination}))notice(destination?'Заявка перемещена':'Заявка снова группируется по дате начала');
    },
  });
  const folderButton=(key,label,count,icon=<Folder size={15}/>)=> <button type="button" className="mw-folder" aria-pressed={folder===key} onClick={()=>browse(key)}>{icon}<span>{label}</span>{count!=null&&<b>{count}</b>}</button>;
  const folderPath=item=>{const names=[item.name];let current=item;const seen=new Set([item.id]);while(current.parent_id){current=model.folders.find(candidate=>candidate.id===current.parent_id);if(!current||seen.has(current.id))break;seen.add(current.id);names.unshift(current.name)}return names.join(' / ')};
  const renderFolders=(parentId=null,depth=0)=>model.folders.filter(item=>(item.parent_id||null)===parentId).sort((a,b)=>Number(Boolean(b.pinned))-Number(Boolean(a.pinned))).map(item=>{
    const hasChildren=model.folders.some(child=>child.parent_id===item.id);
    const bookingDrop=dropProps(item.id);
    return <div className="mw-folder-branch" key={item.id} style={{'--folder-depth':depth}}><div className={`mw-custom ${dropFolder===item.id?'is-drop-target':''} ${folderDrop===item.id?'is-folder-drop':''}`} onDragOver={event=>{if(folderDragging){event.preventDefault();event.stopPropagation();setFolderDrop(item.id)}else bookingDrop.onDragOver(event)}} onDragLeave={bookingDrop.onDragLeave} onDrop={event=>{if(folderDragging){event.preventDefault();event.stopPropagation();moveFolder(folderDragging,item.id);setFolderDragging(null);setFolderDrop(null)}else bookingDrop.onDrop(event)}}>
      <button type="button" className="mw-folder-toggle" disabled={!hasChildren} title={hasChildren?(item.collapsed?'Показать подпапки':'Скрыть подпапки'):''} aria-label={hasChildren?(item.collapsed?`Показать подпапки папки ${item.name}`:`Скрыть подпапки папки ${item.name}`):'Подпапок нет'} onClick={()=>hasChildren&&patchFolder(item.id,{collapsed:!item.collapsed})}>{hasChildren?(item.collapsed?<ChevronRight size={15}/>:<ChevronDown size={15}/>):<span/>}</button>
      <button type="button" className="mw-folder-grip" draggable disabled={saving} title="Перетащить папку" aria-label={`Перетащить папку ${item.name}`} onDragStart={event=>{event.stopPropagation();event.dataTransfer.effectAllowed='move';event.dataTransfer.setData('text/plain',item.id);setFolderDragging(item.id)}} onDragEnd={()=>{setFolderDragging(null);setFolderDrop(null)}}><GripVertical size={14}/></button>
      {editing===item.id?<form className="mw-rename" onSubmit={event=>renameFolder(event,item)}><input autoFocus value={name} onChange={event=>setName(event.target.value)} onBlur={event=>renameFolder(event,item)} onKeyDown={event=>{if(event.key==='Escape'){event.preventDefault();setEditing(null);setName('')}}} maxLength={70} aria-label={`Новое название папки ${item.name}`}/></form>:folderButton(item.id,item.name,item.pinned?null:undefined,item.pinned?<Pin size={14} fill="currentColor"/>:<Folder size={15}/>) }
      <button type="button" title="Добавить подпапку" aria-label={`Добавить подпапку в ${item.name}`} disabled={saving} onClick={()=>{setCreatingFolder({parentId:item.id});setName('')}}><Plus size={14}/></button>
      <button type="button" title="Переименовать" aria-label={`Переименовать папку ${item.name}`} disabled={saving} onClick={()=>{setEditing(item.id);setCreatingFolder(null);setName(item.name)}}><Pencil size={14}/></button>
      <button type="button" className={item.pinned?'active-pin':''} title={item.pinned?'Открепить папку':'Закрепить папку'} aria-label={item.pinned?`Открепить папку ${item.name}`:`Закрепить папку ${item.name}`} disabled={saving} onClick={()=>patchFolder(item.id,{pinned:!item.pinned})}><Pin size={14} fill={item.pinned?'currentColor':'none'}/></button>
      <button type="button" title="Удалить" aria-label={`Удалить папку ${item.name}`} disabled={saving} onClick={()=>remove(item)}><Trash2 size={14}/></button>
    </div>{creatingFolder?.parentId===item.id&&<form className="mw-create mw-create-child" onSubmit={addFolder}><input autoFocus value={name} onChange={e=>setName(e.target.value)} onKeyDown={e=>{if(e.key==='Escape'){setCreatingFolder(null);setName('')}}} maxLength={70} placeholder="Название подпапки и Enter" aria-label={`Название подпапки для ${item.name}`}/></form>}{!item.collapsed&&renderFolders(item.id,depth+1)}</div>
  });
  const closeContext=()=>{setContext(null);setContextPanel(null)};
  const openContext=(event,group)=>{
    event.preventDefault();event.stopPropagation();setEditing(null);setContextPanel(null);
    setContext({group,x:Math.max(10,Math.min(event.clientX,window.innerWidth-310)),y:Math.max(10,Math.min(event.clientY,window.innerHeight-470))});
  };
  const runAction=async action=>{closeContext();await action()};
  return <section className={bookingMode?'mw-page':'content-page moderation-page mw-page'}>
    {!bookingMode&&<><div className="page-heading"><div><small>РАБОЧАЯ ОЧЕРЕДЬ</small><h1>Модерация заявок</h1></div></div><section className="admin-booking-filters moderation-filters" aria-label="Фильтры заявок"><header><div><Search/>{filterCount>0&&<span>{filterCount}</span>}</div><small>{groups.length} записей</small>{filterCount>0&&<button type="button" onClick={()=>setFilters(emptyFilters)}><RotateCcw/>Сбросить</button>}</header><div className="admin-booking-filter-grid"><label><span>ФИО ответственного</span><input value={filters.responsible} onChange={e=>updateFilter('responsible',e.target.value)} placeholder="Введите ФИО"/></label><label><span>Название программы</span><input value={filters.title} onChange={e=>updateFilter('title',e.target.value)} placeholder="Введите название"/></label><label><span>Номер заявки</span><input value={filters.reference} onChange={e=>updateFilter('reference',e.target.value)} placeholder="Введите номер"/></label><label><span>Аудитория</span><input value={filters.room} onChange={e=>updateFilter('room',e.target.value)} placeholder="Например: 2254"/></label><label><span>Корпус</span><select value={filters.building} onChange={e=>updateFilter('building',e.target.value)}><option value="">Все корпуса</option>{buildingOptions.map(value=><option key={value}>{value}</option>)}</select></label><label><span>Подразделение / центр</span><select value={filters.department} onChange={e=>updateFilter('department',e.target.value)}><option value="">Все подразделения</option>{departmentOptions.map(value=><option key={value}>{value}</option>)}</select></label><label><span>Тип мероприятия</span><select value={filters.eventFormat} onChange={e=>updateFilter('eventFormat',e.target.value)}><option value="">Все типы</option>{eventFormatOptions.map(value=><option key={value}>{value}</option>)}</select></label><details className="admin-booking-date-filter"><summary><CalendarRange/>Период проведения</summary><div><label><span>С даты</span><input type="date" value={filters.dateFrom} onChange={e=>updateFilter('dateFrom',e.target.value)}/></label><label><span>По дату</span><input type="date" value={filters.dateTo} onChange={e=>updateFilter('dateTo',e.target.value)}/></label></div></details></div></section></>}
    {failure&&<p className="mw-error" role="alert">{failure} <button type="button" onClick={()=>{setFailure('');setReload(value=>value+1)}}>Обновить</button></p>}
    <div className="mw-workspace" style={{'--mw-sidebar-width':`${sidebarWidth}px`}}>
      <aside aria-label="Папки заявок">
        {!bookingMode&&folderButton('all','Все заявки',groups.length)}
        {!bookingMode&&folderButton('inbox','Поступившие заявки',groups.filter(group=>group.pending).length)}
        {!bookingMode&&folderButton('in-progress','Принятые в работу',groups.filter(group=>group.inProgress).length)}
        {bookingMode&&folderButton('all','Все бронирования',groups.length)}
        {bookingMode&&folderButton('booking-confirmed','Подтверждённые',groups.filter(group=>group.approved&&!group.pending).length)}
        {bookingMode&&folderButton('favorites','Избранное',groups.filter(group=>model.entries[group.key]?.favorite).length,<Star size={15}/>) }
        <div className="mw-folder-heading"><h2>Мои папки</h2><button type="button" className="mw-folder-add" title="Создать папку" aria-label="Создать папку" onClick={()=>{setCreatingFolder({parentId:null});setName('')}}><Plus size={17}/></button></div>
        {dragging&&<div className={`mw-drop-auto ${dropFolder==='auto'?'is-drop-target':''}`} {...dropProps('auto')}>Убрать из папки</div>}
        {renderFolders()}
        {creatingFolder&&creatingFolder.parentId===null&&<form className="mw-create" onSubmit={addFolder}><input autoFocus value={name} onChange={e=>setName(e.target.value)} onKeyDown={e=>{if(e.key==='Escape'){setCreatingFolder(null);setName('')}}} maxLength={70} placeholder="Название папки и Enter" aria-label="Название новой папки"/></form>}
      </aside><div className="mw-resizer" role="separator" aria-label="Изменить ширину панели папок" aria-orientation="vertical" tabIndex="0" onPointerDown={resizeSidebar} onKeyDown={event=>{if(event.key==='ArrowLeft')setSidebarWidth(value=>Math.max(220,value-20));if(event.key==='ArrowRight')setSidebarWidth(value=>Math.min(520,value+20))}}/>
      <div className="mw-content">
        <header><h2>{groupLabel}</h2>{!bookingMode&&<label><Search size={16}/><input value={query} onChange={e=>setQuery(e.target.value)} placeholder="Поиск по заявкам" aria-label="Поиск по заявкам"/></label>}
          <select value={period} onChange={e=>setPeriod(e.target.value)} aria-label="Период по дате начала"><option value="all">Все даты</option><option value="week">Текущая неделя</option><option value="month">Текущий месяц</option><option value="year">Текущий год</option></select>
          <strong className="mw-total-count">Всего заявок: {groups.length}</strong>
        </header>
        <div className={`mw-list ${bookingMode?'booking-list':''}`}><div className="mw-grid mw-head"><span>Статус</span><span>Мероприятие</span><span>Дата начала</span>{bookingMode&&<span>Дата окончания</span>}<span>Ответственный</span><span>Дата подачи</span><span/></div>
          {pageRows.map(group=>{
            const {row,key}=group,entry=model.entries[key]||emptyEntry,review=pendingKeys.get(key);
            const [tone,status]=group.pending?['pending','На модерации']:group.inProgress?['working','Принята в работу']:
              group.approved?['approved','Подтверждена']:group.rejected?['rejected','Отклонена']:['closed','Закрыта'];
            const responsible=row.customer_name||row.booked_by||'—';
            return <article id={'review-'+key} key={key} className={`${key===focusKey?'mw-focused ':''}${group.shortNotice?'mw-short-notice':''}`}>
              <div className="mw-grid mw-clickable-row" role="button" tabIndex={0} onClick={()=>review?openReview(review):openBooking(row)} onKeyDown={event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();review?openReview(review):openBooking(row)}}} onContextMenu={event=>openContext(event,group)} draggable={Boolean(settings)&&!saving} onDragStart={event=>{event.dataTransfer.setData('text/plain',key);event.dataTransfer.effectAllowed='move';setDragging(key)}} onDragEnd={()=>{setDragging(null);setDropFolder(null)}}>
                <span className={'mw-status '+tone}>{status}</span>
                <div className="mw-title"><button type="button" title={row.title} tabIndex={-1} onClick={event=>{event.stopPropagation();review?openReview(review):openBooking(row)}}>{row.title}</button>
                  {entry.tags.length>0&&<div className="mw-tags">{entry.tags.map(tag=><Tag key={tag} value={tag} color={model.tag_colors[tag]}/>)}</div>}
                </div>
                <time>{dateLabel(group.start)}</time>{bookingMode&&<time>{dateLabel(group.end)}</time>}<span className="mw-person" title={responsible}>{responsible}</span><time>{dateLabel(group.submitted)}</time>
                <div className="mw-row-actions"><button type="button" className={`mw-favorite ${entry.favorite?'active':''}`} title={entry.favorite?'Убрать из избранного':'Добавить в избранное'} aria-label={entry.favorite?'Убрать из избранного':'Добавить в избранное'} onClick={event=>{event.stopPropagation();updateEntry(key,{favorite:!entry.favorite})}}><Star size={18} fill={entry.favorite?'currentColor':'none'}/></button></div>
              </div>
            </article>;
          })}
          {!rows.length&&<p className="mw-empty">В этом списке нет заявок по выбранным условиям.</p>}
        </div>
        {rows.length>0&&<nav className="mw-pagination" aria-label="Страницы заявок"><button type="button" disabled={currentPage===1} onClick={()=>setPage(value=>Math.max(1,value-1))}>← Назад</button><span>Страница <b>{currentPage}</b> из <b>{pageCount}</b> · показано {pageRows.length} из {rows.length}</span><button type="button" disabled={currentPage===pageCount} onClick={()=>setPage(value=>Math.min(pageCount,value+1))}>Вперёд →</button></nav>}
      </div>
    </div>
    {context&&(()=>{const {group}=context,{row,key}=group,entry=model.entries[key]||emptyEntry,review=pendingKeys.get(key);const submenuX=context.x+652<window.innerWidth?context.x+304:Math.max(10,context.x-352);const submenuY=Math.max(10,Math.min(context.y+42,window.innerHeight-420));return <><div className="mw-context-menu" style={{left:context.x,top:context.y}} role="menu" aria-label={`Действия с заявкой «${row.title}»`}>
      {!bookingMode&&group.pending&&takeInWork&&<button type="button" role="menuitem" className="mw-menu-work" disabled={actionsBusy} onClick={()=>runAction(()=>takeInWork(review))}><WandSparkles size={16}/>Принять в работу</button>}
      {!bookingMode&&(group.pending||group.inProgress)&&approveRequest&&<button type="button" role="menuitem" className="mw-menu-approve" disabled={actionsBusy} onClick={()=>runAction(()=>approveRequest(review))}>✓ Подтвердить</button>}
      {!bookingMode&&(group.pending||group.inProgress)&&rejectRequest&&<button type="button" role="menuitem" className="mw-menu-reject" disabled={actionsBusy} onClick={()=>{closeContext();rejectRequest(review)}}>× Отклонить</button>}
      {!bookingMode&&(group.pending||group.inProgress)&&<hr/>}
      <button type="button" role="menuitem" onClick={()=>updateEntry(key,{favorite:!entry.favorite})}><Star size={16} fill={entry.favorite?'currentColor':'none'}/>{entry.favorite?'Убрать из избранного':'Добавить в избранное'}</button>
      <button type="button" role="menuitem" onClick={()=>setContextPanel(contextPanel==='tags'?null:'tags')}><Hash size={16}/>Добавить хэштег<ChevronRight className="mw-menu-chevron" size={16}/></button>

      <button type="button" role="menuitem" onClick={()=>setContextPanel(contextPanel==='folder'?null:'folder')}><FolderInput size={16}/>Перенести в папку</button>
      {contextPanel==='folder'&&<div className="mw-context-folders"><button type="button" onClick={()=>runAction(()=>updateEntry(key,{folder:null}))}>Без папки</button>{model.folders.map(item=><button type="button" key={item.id} onClick={()=>runAction(()=>updateEntry(key,{folder:item.id}))}>{folderPath(item)}</button>)}</div>}
      <hr/><button type="button" role="menuitem" onClick={()=>{closeContext();(pendingKeys.get(key)?openReview(pendingKeys.get(key)):openBooking(row))}}><Eye size={16}/>Просмотреть детали</button>
      {bookingMode&&replaceBooking&&!row.series_id&&<button type="button" role="menuitem" onClick={()=>{closeContext();replaceBooking(row)}}><WandSparkles size={16}/>Найти замену</button>}
      {bookingMode&&archiveBooking&&<button type="button" role="menuitem" onClick={()=>{closeContext();archiveBooking(row)}}><Archive size={16}/>{row.archived_at?'Вернуть из архива':'Перенести в архив'}</button>}
      {bookingMode&&deleteBooking&&<button type="button" role="menuitem" className="danger" onClick={()=>{closeContext();deleteBooking(row)}}><Trash2 size={16}/>Удалить</button>}
    </div>{contextPanel==='tags'&&<div className="mw-context-submenu" style={{left:submenuX,top:submenuY}}><TagPicker selected={entry.tags} catalog={model.tag_catalog} colors={model.tag_colors} disabled={!settings||saving} onChange={tags=>updateEntry(key,{tags})} onColorChange={(tag,color)=>save({...model,tag_colors:{...model.tag_colors,[tag]:color}})} onDelete={deleteTag}/></div>}</>})()}
  </section>;
}
