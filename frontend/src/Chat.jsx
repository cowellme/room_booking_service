import {useEffect,useState,useSyncExternalStore} from 'react';
import {Check, CheckCheck, MessageCircle, Paperclip, Search, Send, X} from 'lucide-react';
import './chat.css';

const empty={threads:[],unread:0};
let snapshot=empty;
const listeners=new Set();
const subscribe=fn=>{listeners.add(fn);return ()=>listeners.delete(fn)};
const publish=value=>{snapshot=value;listeners.forEach(fn=>fn())};
const openChat=target=>window.dispatchEvent(new CustomEvent('room-chat-open',{detail:target}));
const json=body=>({method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
const timeLabel=value=>new Date(/(?:Z|[+-]\d{2}:\d{2})$/.test(value)?value:value+'Z').toLocaleString('ru-RU',{day:'numeric',month:'short',hour:'2-digit',minute:'2-digit',hour12:false});

export function BookingChatLink({item}) {
  const inbox=useSyncExternalStore(subscribe,()=>snapshot);
  const target=item.series_id?'series:'+item.series_id:'booking:'+(item.parent_booking_id||item.id);
  const unread=inbox.threads.find(row=>row.target===target)?.unread||0;
  if(item.record_kind!=='booking')return null;
  return <button className="booking-chat-link" type="button" onClick={()=>openChat(target)}>
    <MessageCircle size={18}/>Перейти в чат по заявке{unread>0&&<span className="chat-counter">{unread} новых</span>}
  </button>;
}

function Avatar({name='?',src,online=false}) {
  const [failed,setFailed]=useState(false);
  useEffect(()=>setFailed(false),[src]);
  return <span className={`chat-avatar ${online?'is-online':''}`} aria-hidden="true">{src&&!failed?<img src={src} alt="" onError={()=>setFailed(true)}/>:name.trim().slice(0,1).toUpperCase()||'?'}</span>;
}

function ChatFile({file}) {
  const inline=file.url+'?inline=1';
  if(file.preview==='image')return <a className="chat-file-preview" href={file.url} target="_blank" rel="noopener"><img src={inline} alt={file.name}/><span><Paperclip size={15}/>{file.name}</span></a>;
  if(file.preview==='pdf')return <a className="chat-file-preview" href={file.url} target="_blank" rel="noopener"><iframe src={`${inline}#page=1&view=FitH&toolbar=0&navpanes=0`} title={`Первая страница ${file.name}`} loading="lazy" tabIndex="-1"/><span><Paperclip size={15}/>{file.name}</span></a>;
  return <a className="chat-file" href={file.url}><Paperclip size={15}/>{file.name}</a>;
}

export default function Chat({request,open,navigate,user}) {
  const inbox=useSyncExternalStore(subscribe,()=>snapshot);
  const [target,setTarget]=useState(null),[tab,setTab]=useState('all');
  const [query,setQuery]=useState(''),[people,setPeople]=useState([]),[searchError,setSearchError]=useState('');
  const [data,setData]=useState(null),[older,setOlder]=useState(null),[error,setError]=useState(''),[body,setBody]=useState(''),[sending,setSending]=useState(false),[revision,refresh]=useState(0);
  const [file,setFile]=useState(null);
  const select=next=>{setTarget(next);setData(null);setOlder(null);setBody('');setFile(null);setError('');refresh(n=>n+1)};
  useEffect(()=>{
    let active=true;
    const beat=()=>request('/api/chat/presence',{method:'POST'}).catch(()=>{});
    beat();const timer=setInterval(()=>{if(active)beat()},10000);
    return()=>{active=false;clearInterval(timer)};
  },[request]);
  useEffect(()=>{
    const handler=event=>{select(event.detail);setQuery('');setTab('booking');navigate('chat')};
    window.addEventListener('room-chat-open',handler);
    return ()=>window.removeEventListener('room-chat-open',handler);
  },[navigate]);
  useEffect(()=>{
    let active=true;
    const update=()=>request('/api/chat/inbox').then(value=>{if(active)publish(value)}).catch(()=>{});
    update();
    const timer=setInterval(update,6000);
    return ()=>{active=false;clearInterval(timer);publish(empty)};
  },[request]);
  useEffect(()=>{
    let active=true;
    setPeople([]);setSearchError('');
    if(!open||!query.trim())return;
    const timer=setTimeout(()=>request('/api/chat/people?q='+encodeURIComponent(query.trim()))
      .then(items=>{if(active)setPeople(items)}).catch(e=>{if(active)setSearchError(e.message)}),300);
    return ()=>{active=false;clearTimeout(timer)};
  },[request,query,open]);
  useEffect(()=>{
    if(!open||!target)return;
    let active=true,busy=false,lastRead=0;
    const path='/api/chat/thread/'+encodeURIComponent(target);
    const load=async()=>{
      if(busy)return;
      busy=true;
      try{
        const value=await request(path);
        if(!active)return;
        setData(value);setError('');
        const through=value.messages.filter(item=>!item.mine).at(-1)?.id||0;
        if(through>lastRead&&!document.hidden){
          await request(path+'/read/'+through,{method:'POST'});
          lastRead=through;
          if(active){const value=await request('/api/chat/inbox');if(active)publish(value)}
        }
      }catch(e){if(active)setError(e.message)}
      finally{busy=false}
    };
    load();const timer=setInterval(load,4000);
    return ()=>{active=false;clearInterval(timer)};
  },[request,open,target,revision]);
  useEffect(()=>{
    if(!open||!target||!body.trim())return;
    const path='/api/chat/thread/'+encodeURIComponent(target)+'/typing';
    let active=true;
    const pulse=()=>request(path,json({active:true})).catch(()=>{});
    pulse();const timer=setInterval(()=>{if(active)pulse()},3000);
    return()=>{active=false;clearInterval(timer);request(path,json({active:false})).catch(()=>{})};
  },[request,open,target,body]);
  const submit=async()=>{
    if(sending||!target||(!body.trim()&&!file))return;
    setSending(true);setError('');
    try{
      const path='/api/chat/thread/'+encodeURIComponent(target);
      if(file){
        const content=await new Promise((resolve,reject)=>{
          const reader=new FileReader();
          reader.onerror=()=>reject(new Error('Не удалось прочитать файл'));
          reader.onload=()=>resolve(String(reader.result).split(',',2)[1]);
          reader.readAsDataURL(file);
        });
        await request(path+'/file',json({name:file.name,content,body}));
      }else await request(path,json({body}));
      setBody('');setFile(null);refresh(n=>n+1);
    }catch(e){setError(e.message)}
    finally{setSending(false)}
  };
  const olderMessages=async()=>{
    const marker=(older||data)?.messages[0]?.id;
    if(!marker)return;
    try{
      const value=await request('/api/chat/thread/'+encodeURIComponent(target)+'?before='+marker);
      setOlder(old=>({target,more:value.more,messages:[...value.messages,...(old?.target===target?old.messages:[])]}));
    }catch(e){setError(e.message)}
  };
  const entries=[...new Map([...(older?.target===target?older.messages:[]),...(data?.messages||[])].map(item=>[item.id,item])).values()];
  const threads=inbox.threads.filter(item=>tab==='all'||(tab==='person')===item.target.startsWith('person:'));
  const unreadFor=key=>key==='all'?inbox.unread:inbox.threads.filter(item=>(key==='person')===item.target.startsWith('person:')).reduce((sum,item)=>sum+item.unread,0);
  return <>
    {!open&&<button className="chat-launcher" type="button" aria-label={`Чаты, непрочитанных: ${inbox.unread}`} onClick={()=>{select(null);setQuery('');setTab('all');navigate('chat')}}>
      <MessageCircle size={30}/>{inbox.unread>0&&<span className="chat-counter">{inbox.unread>99?'99+':inbox.unread}</span>}
    </button>}
    {open&&<section className="chat-panel" aria-labelledby="chat-page-title">
        <header><h1 id="chat-page-title"><MessageCircle size={25}/>Сообщения</h1><button type="button" onClick={()=>navigate('bookings')}>Мои бронирования</button></header>
        <div className={`chat-workspace ${target?'has-thread':''}`}>
          <aside>
            <label className="chat-search"><Search size={18}/><input placeholder="Найти коллегу по имени" aria-label="Найти коллегу" value={query} onChange={e=>setQuery(e.target.value)} autoFocus={!target}/></label>
            {query.trim()?<div className="chat-thread-list chat-people-results">{searchError?<p role="alert">{searchError}</p>:people.length?people.map(item=><button type="button" key={item.target} onClick={()=>{select(item.target);setQuery('')}}><Avatar name={item.title} src={item.avatar_url} online={item.online}/><span>{item.title}</span></button>):<p>Нет совпадений</p>}</div>:<>
              <div className="chat-tabs" aria-label="Виды чатов">{[['all','Все'],['person','Коллеги'],['booking','По заявкам']].map(([key,title])=>{const unread=unreadFor(key);return <button type="button" key={key} aria-pressed={tab===key} onClick={()=>setTab(key)}>{title}{unread>0&&<span className="chat-tab-badge">{unread>99?'99+':unread}</span>}</button>})}</div>
              <div className="chat-thread-list">{threads.length?threads.map(item=><button type="button" key={item.target} className={target===item.target?'active':''} onClick={()=>select(item.target)}><Avatar name={item.peer_name||item.title} src={item.avatar_url} online={item.online}/><span className="chat-thread-text"><strong>{item.title}</strong>{item.typing?<small className="chat-typing">печатает…</small>:item.last&&<small><span className="chat-list-receipt" title={item.last.read?'Прочитано':'Не прочитано'}>{item.last.read?<CheckCheck size={14}/>:<Check size={14}/>}</span><b>{item.last.mine?'Вы':item.peer_name}:</b> {item.last.text}</small>}</span>{item.unread>0&&<span className="chat-counter">+{item.unread}</span>}</button>):<p>Здесь появятся ваши чаты</p>}</div>
            </>}
          </aside>
          {target?<section className="chat-conversation">
            <h3><button type="button" onClick={()=>select(null)}>‹ Чаты</button><Avatar name={data?.peer_name} src={data?.avatar_url} online={data?.online}/><span className="chat-peer-heading"><b>{data?.title||'Сообщения'}</b>{data?.typing?<em>печатает…</em>:data?.online&&<small>онлайн</small>}</span></h3>
            <div className="chat-messages" aria-label="Сообщения">
              {(older?.target===target?older.more:data?.more)&&<button type="button" onClick={olderMessages}>Показать более ранние</button>}
              {entries.map(item=><div className={`chat-message-row ${item.mine?'mine':''}`} key={item.id}><Avatar name={item.mine?user?.full_name:data?.peer_name} src={item.mine?user?.avatar_url:data?.avatar_url} online={!item.mine&&data?.online}/><article className={item.mine?'mine':''}>{item.body&&<div>{item.body}</div>}{item.file&&<ChatFile file={item.file}/>}<footer><time>{timeLabel(item.at)}</time>{item.mine&&<span className="chat-receipt" role="img" aria-label={item.read?'Прочитано':'Доставлено, не прочитано'} title={item.read?'Прочитано':'Доставлено, не прочитано'}>{item.read?<CheckCheck size={16}/>:<Check size={16}/>}</span>}</footer></article></div>)}
              {data?.typing&&<div className="chat-live-typing"><Avatar name={data.peer_name} src={data.avatar_url} online={data.online}/><em>печатает…</em></div>}
              {data&&!entries.length&&<p>Сообщений пока нет. Напишите первым.</p>}
            </div>
            {error&&<p className="chat-error" role="alert">{error}</p>}
            {data&&<form onSubmit={event=>{event.preventDefault();submit()}}>
              <label className="chat-file-picker" title="Прикрепить файл до 5 МБ"><Paperclip size={22}/><input type="file" aria-label="Прикрепить файл" disabled={sending} onChange={e=>{const selected=e.target.files?.[0];e.target.value='';if(!selected)return;if(!selected.size||selected.size>5*1024*1024){setError('Выберите файл размером до 5 МБ');return}setError('');setFile(selected)}}/></label>
              <div className="chat-compose">{file&&<div className="chat-file-chip"><span>{file.name}</span><button type="button" aria-label="Убрать файл" disabled={sending} onClick={()=>setFile(null)}><X size={14}/></button></div>}
              <textarea aria-label="Текст сообщения" placeholder="Текст сообщения" value={body} maxLength={4000} onChange={e=>setBody(e.target.value)} onKeyDown={e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.nativeEvent.isComposing){e.preventDefault();submit()}}}/></div>
              <button className="primary" disabled={sending||(!body.trim()&&!file)} aria-label="Отправить"><Send size={21}/></button></form>}
          </section>:<div className="chat-empty"><MessageCircle size={34}/><p>Выберите переписку или найдите коллегу</p></div>}
        </div>
    </section>}
  </>;
}
