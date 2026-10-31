import test from 'node:test';
import assert from 'node:assert/strict';
import {eventFinished} from '../src/bookingCenterConfig.js';

const item={date:'2030-01-14',time_start:'10:00',time_end:'12:00'};
for(const value of ['2030-01-13T23:59:59','2030-01-14T09:59:59','2030-01-14T10:00:00','2030-01-14T10:30:00','2030-01-14T11:59:59.999']){
  test(`completion unavailable before end: ${value}`,()=>assert.equal(eventFinished(item,new Date(value)),false));
}
for(const value of ['2030-01-14T12:00:00','2030-01-14T12:00:01','2030-01-15T00:00:00']){
  test(`completion available at/after end: ${value}`,()=>assert.equal(eventFinished(item,new Date(value)),true));
}
test('invalid or incomplete schedule cannot enable completion',()=>{
  for(const item of [{},{date:'2030-01-14'},{date:'invalid',time_end:'12:00'}]){
    assert.equal(eventFinished(item,new Date('2030-01-14T13:00:00')),false);
  }
});
