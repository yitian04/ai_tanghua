import test from 'node:test';
import assert from 'node:assert/strict';
import {itemOutside} from '../apps/gui/components/layout_canvas.js';

const item={x_mm:50,y_mm:50,scale:1,rotation_deg:0,paths:[[[-10,-5],[10,5]]]};
test('list and canvas bounds include translation, rotation and scale',()=>{
  assert.equal(itemOutside(item,100,100),false);
  assert.equal(itemOutside({...item,x_mm:5},100,100),true);
  assert.equal(itemOutside({...item,x_mm:5,rotation_deg:90},100,100),false);
  assert.equal(itemOutside({...item,x_mm:5,rotation_deg:90,scale:2},100,100),true);
});
test('edge tolerance matches the composition exporter',()=>{
  assert.equal(itemOutside({...item,x_mm:10-5e-8},100,100),false);
  assert.equal(itemOutside({...item,x_mm:10-2e-7},100,100),true);
});
