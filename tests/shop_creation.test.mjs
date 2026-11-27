import test from 'node:test';
import assert from 'node:assert/strict';
import {distanceToSegment,wheelAngle} from '../apps/gui/components/shop_creation.js';

test('eraser targets segment interiors and endpoints, including zero-length segments',()=>{
  assert.equal(distanceToSegment([5,2],[0,0],[10,0]),2);
  assert.equal(distanceToSegment([12,0],[0,0],[10,0]),2);
  assert.equal(distanceToSegment([3,4],[0,0],[0,0]),5);
});
test('every wheel outcome finishes under the top pointer',()=>{
  for(let index=0;index<7;index++){
    const angle=(wheelAngle(index)+index*360/7)%360;
    assert.ok(Math.abs(angle)<1e-9);
  }
});
