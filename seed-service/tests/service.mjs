import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { readSeed } from '../lib/seed-wire.mjs';
import { handle } from '../netlify/functions/seeds.mjs';

const fixtures=JSON.parse(fs.readFileSync(new URL('./wire-fixtures.json',import.meta.url),'utf8'));
test('WWBS5 finite casts and F execution restore exact values without changing WWBS4',()=>{
  const fixture=JSON.parse(fs.readFileSync(new URL('../../tests/fixtures/counted-casts-seed.json',import.meta.url),'utf8'));
  assert.deepEqual(readSeed(fixture.seed).axis,fixture.axis);
  assert.throws(()=>readSeed(fixture.seed.replace('】WWBS5.','】WWBS4.')));
});
class Store {
  values=new Map();
  async setJSON(key,value,{onlyIfNew}={}) {
    if(onlyIfNew&&this.values.has(key))return {modified:false};
    this.values.set(key,structuredClone(value));return {modified:true};
  }
  async get(key) {return structuredClone(this.values.get(key)||null);}
  async *list({prefix}) {yield {blobs:[...this.values.keys()].filter(k=>k.startsWith(prefix)).sort().map(key=>({key}))};}
}
const request=(method,query='',payload)=>new Request('https://library.example/seeds'+query,
  {method,headers:{'Content-Type':'application/json'},body:payload===undefined?undefined:JSON.stringify(payload)});

test('Python-generated data restores the same axes with every action and exact decimals',()=>{
  for(const fixture of fixtures)assert.deepEqual(readSeed(fixture.seed).axis,fixture.axis);
});

test('WWBS4 prefix and legacy 4 prefix decode to the same immutable record',()=>{
  for(const fixture of fixtures) {
    const branded=fixture.seed.replace('】4.','】WWBS4.');
    assert.deepEqual(readSeed(branded).axis,fixture.axis);
    assert.equal(readSeed(branded).id,readSeed(fixture.seed).id);
  }
});
test('Changed named prefix and truncated or unsupported code are rejected',()=>{
  const code=fixtures[0].seed;
  for(const seed of [code.replace('默认','其他'),code.slice(0,-3),code.replace('】4.','】9.'),'anything'])
    assert.throws(()=>readSeed(seed));
});
test('Upload, partial-name search, and download preserve the seed',async()=>{
  const store=new Store();
  const upload=await handle(request('POST','',{seed:fixtures[0].seed}),store);
  assert.equal(upload.status,201);
  const {item}=await upload.json();
  const result=await (await handle(request('GET','?name='+encodeURIComponent('战斗')),store)).json();
  assert.equal(result.items.length,1);
  assert.equal(result.items[0].id,item.id);
  assert.equal(result.items[0].seed,undefined);
  const downloaded=await (await handle(request('GET','?id='+item.id),store)).json();
  assert.equal(downloaded.item.seed,fixtures[0].seed);
});
test('Duplicate uploads are idempotent and do not replace the original',async()=>{
  const store=new Store();
  await handle(request('POST','',{seed:fixtures[0].seed}),store);
  const duplicate=await handle(request('POST','',{seed:fixtures[0].seed}),store);
  assert.equal(duplicate.status,200);
  assert.equal((await duplicate.json()).duplicate,true);
  assert.equal([...store.values.keys()].filter(k=>k.startsWith('records/')).length,1);
});
test('Invalid data, oversized payloads and unknown IDs never create records',async()=>{
  const store=new Store();
  assert.equal((await handle(request('POST','',{seed:'execute something'}),store)).status,400);
  assert.equal((await handle(request('POST','',{seed:'a'.repeat(33000)}),store)).status,413);
  assert.equal((await handle(request('GET','?id=../anything'),store)).status,400);
  assert.equal((await handle(request('GET','?id='+'a'.repeat(24)),store)).status,404);
  assert.equal(store.values.size,0);
});
test('A failed index write can be repaired by retry without losing a record',async()=>{
  const store=new Store(), original=store.setJSON.bind(store);
  let fail=true;
  store.setJSON=async (key,...args)=>{if(fail&&key.startsWith('index/'))throw new Error('storage unavailable'); return original(key,...args);};
  assert.equal((await handle(request('POST','',{seed:fixtures[0].seed}),store)).status,503);
  fail=false;
  assert.equal((await handle(request('POST','',{seed:fixtures[0].seed}),store)).status,200);
  const result=await (await handle(request('GET','?name='+encodeURIComponent('默认')),store)).json();
  assert.equal(result.items.length,1);
});
test('A storage failure returns a useful error instead of a partial response',async()=>{
  const result=await handle(request('GET','?id='+'a'.repeat(24)),{get:async()=>{throw new Error('offline');}});
  assert.equal(result.status,503);
  assert.match((await result.json()).error,/稍后/);
});

test('Browse and name search return the latest 50 across all pages before truncation',async()=>{
  const store=new Store();
  for(let i=0;i<75;i++) {
    const id=i.toString(16).padStart(24,'0');
    const record={id,name:'测试'+i,modules:18,created:new Date(1700000000000+i*1000).toISOString()};
    await store.setJSON('records/'+id,record);
    await store.setJSON('index/'+Buffer.from('测').toString('hex')+'/'+Buffer.from(record.name).toString('hex')+'/'+id,record);
  }
  const list=store.list.bind(store);
  store.list=async function* (options) {
    for await(const page of list(options))
      for(let i=0;i<page.blobs.length;i+=9)yield {blobs:page.blobs.slice(i,i+9)};
  };
  for(const query of ['', '?name='+encodeURIComponent('测试')]) {
    const result=await (await handle(request('GET',query),store)).json();
    assert.equal(result.items.length,50);
    assert.equal(result.truncated,true);
    assert.deepEqual(result.items.map(item=>item.name),Array.from({length:50},(_,i)=>'测试'+(74-i)));
    assert.ok(result.items.every(item=>item.seed===undefined));
  }
});
