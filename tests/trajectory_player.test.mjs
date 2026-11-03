import test from 'node:test';
import assert from 'node:assert/strict';
import {Playback} from '../apps/gui/components/trajectory_player.js';

function sample(){return {points:[[0,0,10,false],[0,0,0,false],[0,0,0,true],[10,0,0,true],[10,0,10,false],[10,5,10,false],[10,5,0,false],[10,5,0,true],[20,5,0,true],[20,5,10,false]],times:[0,1,1,3,4,5,6,6,8,9],duration_s:9,strokes:[{start:2,end:3},{start:7,end:8}],point_strokes:[1,1,1,1,2,2,2,2,2,2]};}
test('target command, pure Z motion, zero-duration switches and pause',()=>{
  const p=new Playback(sample());p.play();p.advance(.5);assert.equal(p.position().z,5);assert.equal(p.position().drawing,false);
  p.advance(.5);assert.equal(p.index,2);assert.equal(p.position().drawing,true);
  p.advance(1);assert.equal(p.position().x,5);p.pause();p.advance(100);assert.equal(p.position().x,5);
});
test('stroke seeks and restart preserve playing state and multiplier',()=>{
  const p=new Playback(sample());assert.equal(p.seekStroke(2),true);assert.equal(p.index,7);assert.equal(p.playing,false);
  p.restart();assert.equal(p.index,0);assert.equal(p.playing,false);
  p.setSpeed(2);p.play();p.seekStroke(2);assert.equal(p.playing,true);p.advance(.25);assert.equal(p.position().x,12.5);
  p.restart();assert.equal(p.time,0);assert.equal(p.playing,true);assert.equal(p.speed,2);
});
test('invalid seeks and speeds do not change the cursor',()=>{
  const p=new Playback(sample());p.seekStroke(2);
  for(const number of[0,3,1.5,NaN,Infinity]){assert.equal(p.seekStroke(number),false);assert.equal(p.index,7);}
  for(const speed of[0,3,-1,NaN]){assert.equal(p.setSpeed(speed),false);assert.equal(p.speed,1);}
});
test('end pauses; pressing play replays from start',()=>{
  const p=new Playback(sample());p.play();p.advance(100);assert.equal(p.index,9);assert.equal(p.ended,true);assert.equal(p.playing,false);
  p.play();assert.equal(p.time,0);assert.equal(p.ended,false);assert.equal(p.playing,true);
});
test('equal timestamps retain exact paused stroke anchors',()=>{
  const data={points:[[0,0,0,true],[0,0,0,false],[0,0,0,true]],times:[0,0,0],duration_s:0,strokes:[{start:0,end:0},{start:2,end:2}],point_strokes:[1,2,2]};
  const p=new Playback(data);p.seekStroke(1);assert.equal(p.index,0);p.seekStroke(2);assert.equal(p.index,2);assert.equal(p.position().stroke,2);
  p.restart();p.play();assert.equal(p.playing,false);assert.equal(p.ended,true);assert.equal(p.index,2);
});
test('repeated navigation never mutates source or accumulates cursor drift',()=>{
  const data=sample(),original=JSON.stringify(data),p=new Playback(data);
  for(let n=0;n<1000;n++){p.play();p.advance(.1);p.seekStroke(2);p.restart();p.pause();p.seekStroke(1);assert.equal(p.time,1);assert.equal(p.index,2);}
  assert.equal(JSON.stringify(data),original);
});
