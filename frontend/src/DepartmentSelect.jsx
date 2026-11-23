import {useEffect, useRef, useState} from 'react';
import {Check, ChevronDown} from 'lucide-react';

export default function DepartmentSelect({items=[],value='',onChange,placeholder='Выберите подразделение',required=false}){
  const [open,setOpen]=useState(false);
  const [query,setQuery]=useState('');
  const root=useRef(null);
  const selected=items.find(item=>String(item.id)===String(value));
  const normalized=query.trim().toLocaleLowerCase('ru-RU');
  const filtered=normalized?items.filter(item=>item.name.toLocaleLowerCase('ru-RU').includes(normalized)):items;
  useEffect(()=>{
    if(!open)return;
    const close=event=>{if(!root.current?.contains(event.target))setOpen(false)};
    document.addEventListener('pointerdown',close);
    return()=>document.removeEventListener('pointerdown',close);
  },[open]);
  const close=()=>{setOpen(false);setQuery('')};
  return <div className={`department-select ${open?'open':''}`} ref={root}>
    <div className="department-select-trigger">
      <input value={open?query:(selected?.name||'')} required={required} onFocus={()=>{setQuery('');setOpen(true)}} onChange={event=>{setQuery(event.target.value);setOpen(true)}} onKeyDown={event=>{if(event.key==='Escape'){close();event.currentTarget.blur()}}} placeholder={open?'Введите название подразделения':placeholder} role="combobox" aria-autocomplete="list" aria-expanded={open}/>
      <button type="button" onClick={()=>open?close():(setQuery(''),setOpen(true))} aria-label={open?'Закрыть список':'Открыть список'}><ChevronDown/></button>
    </div>
    {open&&<div className="department-select-menu" role="listbox">
      {filtered.length?filtered.map(item=><button type="button" role="option" aria-selected={String(item.id)===String(value)} className={String(item.id)===String(value)?'selected':''} onClick={()=>{onChange?.(String(item.id),item);close()}} key={item.id}><span>{item.name}</span>{String(item.id)===String(value)&&<Check/>}</button>):<p className="department-select-empty">Подразделение не найдено</p>}
    </div>}
  </div>
}
