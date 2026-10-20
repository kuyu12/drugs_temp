const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const read = name => JSON.parse(fs.readFileSync(path.join(__dirname, name), 'utf8'));
const collection = read('medical-devices.postman_collection.json');
const env = Object.fromEntries(read('medical-devices.postman_environment.json').values.map(v => [v.key,v.value]));
const local = {};
let response;
function expect(value, negate = false) {
  const c = {
    equal(other) { negate ? assert.notStrictEqual(value,other) : assert.strictEqual(value,other); return expect(value); },
    a(type) { assert.strictEqual(type === 'array' ? Array.isArray(value) : typeof value === type, !negate); return expect(value); },
    an(type) { return this.a(type); },
    property(key) { assert.strictEqual(value != null && Object.prototype.hasOwnProperty.call(value,key),!negate); return expect(value); },
  };
  for (const name of ['to','be','have','and','that','is']) Object.defineProperty(c,name,{get:()=>c});
  Object.defineProperty(c,'not',{get:()=>expect(value,!negate)});
  Object.defineProperty(c,'empty',{get:()=>{assert.strictEqual(value.length === 0,!negate);return expect(value);}});
  return c;
}
const pm = {expect, test:(name,fn)=>fn(),
  environment:{get:k=>env[k],set:(k,v)=>env[k]=v,unset:k=>delete env[k]},
  variables:{set:(k,v)=>local[k]=v},
  response:{code:200,json:()=>response,headers:{get:()=> 'application/json'},
    to:{have:{status:n=>assert.equal(pm.response.code,n)}}}};
function run(item,phase) {for (const e of item.event || []) if (e.listen===phase) new Function('pm',e.script.exec.join('\n'))(pm);}
function tests(index) {run(collection,'test');run(collection.item[index],'test');}
for (const item of [collection,...collection.item]) for (const e of item.event || []) new Function('pm',e.script.exec.join('\n'));
assert.equal(collection.item.length,5);
assert.throws(()=>run(collection.item[1],'prerequest'));
run(collection.item[0],'prerequest');
assert.equal(JSON.parse(local.request_json).pageNumber,0);
response={statusCode:200,returnObject:{totalRows:1,medicalAccessoriesList:[{registrationNumber:'25320001'}]}};
tests(0);run(collection.item[1],'prerequest');
assert.strictEqual(JSON.parse(local.request_json).registrationNumber,25320001);
response.returnObject.totalRows=0;tests(1);
response.returnObject.medicalAccessoriesList[0].registrationNumber='9';assert.throws(()=>tests(1));
for (let i=2;i<5;i++) {
  run(collection.item[i],'prerequest');
  response={statusCode:200,returnObject:[{key:0,name:'example'}]};tests(i);
}
env.search_text='changed';assert.throws(()=>run(collection.item[1],'prerequest'));
pm.response.code=403;assert.throws(()=>run(collection,'test'));
console.log('Postman scripts, assertions, numeric registration and filter isolation: PASS');
