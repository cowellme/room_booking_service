import {useEffect} from 'react';

// Scroll the calendar itself, even when the pointer is over a booking card or
// the inner records list. Touch/pen gestures retain the browser's native pan.
export default function useCalendarGestures(scrollRef){
  useEffect(()=>{
    const area=scrollRef.current;if(!area)return;
    let drag=null,suppressClick=false;
    const finish=()=>{
      const previous=drag;drag=null;
      area.classList.remove('is-dragging');
      if(previous?.moved)suppressClick=true;
      if(previous&&area.hasPointerCapture(previous.id))area.releasePointerCapture(previous.id);
    };
    const down=event=>{
      if(event.pointerType!=='mouse'||event.button!==0||event.ctrlKey||event.metaKey||event.altKey)return;
      if(event.target.closest('input,textarea,select,[contenteditable="true"]'))return;
      const box=area.getBoundingClientRect();
      // Leave the native scrollbars usable too.
      if(event.clientX>=box.left+area.clientWidth||event.clientY>=box.top+area.clientHeight)return;
      suppressClick=false;
      drag={id:event.pointerId,x:event.clientX,y:event.clientY,left:area.scrollLeft,top:area.scrollTop,moved:false};
    };
    const move=event=>{
      if(!drag||event.pointerId!==drag.id)return;
      if(!(event.buttons&1)){finish();return}
      const dx=event.clientX-drag.x,dy=event.clientY-drag.y;
      if(!drag.moved&&Math.hypot(dx,dy)<6)return;
      if(!drag.moved){drag.moved=true;area.classList.add('is-dragging');area.setPointerCapture(drag.id)}
      event.preventDefault();
      area.scrollLeft=drag.left-dx;
      area.scrollTop=drag.top-dy;
    };
    const up=event=>{if(drag?.id===event.pointerId)finish()};
    const click=event=>{
      if(suppressClick&&event.detail>0){suppressClick=false;event.preventDefault();event.stopImmediatePropagation()}
    };
    const wheel=event=>{
      if(event.ctrlKey||event.metaKey)return; // preserve browser zoom / pinch
      let dx=event.deltaX,dy=event.deltaY;
      if(event.shiftKey&&!dx){dx=dy;dy=0}
      if(event.deltaMode===1){dx*=16;dy*=16}
      if(event.deltaMode===2){dx*=area.clientWidth;dy*=area.clientHeight}
      const left=area.scrollLeft,top=area.scrollTop;
      area.scrollLeft+=dx;area.scrollTop+=dy;
      if(area.scrollLeft!==left||area.scrollTop!==top)event.preventDefault();
    };
    const preventNativeDrag=event=>event.preventDefault();
    area.addEventListener('pointerdown',down,true);
    window.addEventListener('pointermove',move,{capture:true,passive:false});
    window.addEventListener('pointerup',up,true);
    window.addEventListener('pointercancel',up,true);
    window.addEventListener('blur',finish);
    area.addEventListener('lostpointercapture',up,true);
    area.addEventListener('click',click,true);
    area.addEventListener('dragstart',preventNativeDrag,true);
    area.addEventListener('wheel',wheel,{capture:true,passive:false});
    return()=>{
      finish();
      area.removeEventListener('pointerdown',down,true);
      window.removeEventListener('pointermove',move,true);
      window.removeEventListener('pointerup',up,true);
      window.removeEventListener('pointercancel',up,true);
      window.removeEventListener('blur',finish);
      area.removeEventListener('lostpointercapture',up,true);
      area.removeEventListener('click',click,true);
      area.removeEventListener('dragstart',preventNativeDrag,true);
      area.removeEventListener('wheel',wheel,true);
    };
  },[scrollRef]);
}
