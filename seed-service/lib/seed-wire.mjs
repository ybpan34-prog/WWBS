import { inflateRawSync } from 'node:zlib';
import { createHash } from 'node:crypto';

const DICT = Buffer.from('00000019000f00050f00050607086901232569011422292269011e27690150600064', 'hex');
const ACTIONS = [
  ['idle_attack',20,0,1,100,true], ['attack_count',15,0,1,100,true], ['jump_attack',3,0,1,20,true],
  ['attack_seconds',3,0,.2,30,false], ['heavy_count',1,0,1,20,true], ['skill',1,5,1,1,true],
  ['ultimate',1,15,1,1,true], ['echo',1,20,1,1,true], ['approach',.09,.75,.05,3,false], ['wait',1,0,.2,30,false],
];
const ORDERS = [[1,2,3],[1,3,2],[2,1,3],[2,3,1],[3,1,2],[3,2,1]];
const ACTIONS_V5 = [...ACTIONS, ['execute',1,0,1,1,true], ['skill_count',1,0,1,20,true], ['ultimate_count',1,0,1,20,true]];

export function crc32(buffer) {
  let crc = 0xffffffff;
  for (const byte of buffer) {
    crc ^= byte;
    for (let i=0;i<8;i++) crc = (crc>>>1) ^ ((crc&1) ? 0xedb88320 : 0);
  }
  return (crc^0xffffffff)>>>0;
}

export function readSeed(seed) {
  if (typeof seed !== 'string' || seed.length > 24000) throw new Error('种子过长或格式错误');
  const match = /^【([^【】\r\n]+)】(?:WWBS5|(?:WWBS)?4)\.([A-Za-z0-9_-]+)$/.exec(seed.trim());
  if (!match) throw new Error('请上传当前版本生成的完整种子');
  const actions = seed.trim().includes('】WWBS5.') ? ACTIONS_V5 : ACTIONS;
  const name = match[1];
  if (name.trim() !== name || Array.from(name).length > 10 || /[\u0000-\u001f]/.test(name)) throw new Error('种子名称须为1到10个字');
  const packet = Buffer.from(match[2], 'base64url');
  if (packet.length < 17 || packet.toString('base64url') !== match[2]) throw new Error('种子内容不完整');
  const body = packet.subarray(0,-4);
  if (crc32(Buffer.concat([Buffer.from(name),body])) !== packet.readUInt32LE(packet.length-4)) throw new Error('种子校验失败');
  let raw = body.subarray(13);
  if (body[0] === 2) {
    if (raw.length) throw new Error('种子格式错误');
    raw = DICT;
  } else if (body[0] === 1) {
    const inflated = inflateRawSync(raw, {dictionary: DICT, maxOutputLength:32768, info:true});
    if(inflated.engine.bytesWritten!==raw.length)throw new Error('种子压缩格式错误');
    raw = inflated.buffer;
  } else if (body[0] !== 0) throw new Error('不支持该种子版本');
  let offset=0;
  const take = (n) => { if (offset+n>raw.length) throw new Error('种子内容不完整'); const result=raw.subarray(offset,offset+n); offset+=n; return result; };
  const uint = () => {
    let value=0;
    for(let shift=0;shift<35;shift+=7) { const part=take(1)[0]; value+=(part&127)*2**shift; if(!(part&128)) return value; }
    throw new Error('种子数字错误');
  };
  const number = () => { const tag=take(1)[0]; if(tag===0)return uint(); if(tag===1)return uint()/100; if(tag===2)return take(8).readDoubleLE(); throw new Error('种子数字错误'); };
  const flag=take(1)[0];
  let originalName=name;
  if(flag===1) {
    const length=uint();
    if(length<1||length>256)throw new Error('原预设名称过长');
    originalName=new TextDecoder('utf-8',{fatal:true}).decode(take(length));
  } else if(flag!==0)throw new Error('种子名称错误');
  if(!originalName.trim()||Array.from(originalName).length>64)throw new Error('原预设名称错误');
  const order=take(1)[0];
  if(order>=ORDERS.length)throw new Error('角色顺序错误');
  const times=[number(),number(),number()];
  if(times.some(n=>!Number.isFinite(n)||n<.2||n>120))throw new Error('驻场时间错误');
  const count=uint();
  if(count<1||count>100)throw new Error('模块数量错误');
  const modules=[], idleSlots=new Set();
  for(let i=0;i<count;i++) {
    const header=take(1)[0], index=header&15, slot=((header>>>4)&3)+1;
    if(index>=actions.length||slot>3)throw new Error('模块类型错误');
    const [kind,defaultValue,defaultInterval,low,high,integer]=actions[index];
    const value=header&64?number():defaultValue, interval=header&128?number():defaultInterval;
    if(!Number.isFinite(value)||!Number.isFinite(interval)||value<low||value>high||interval<0||interval>120||
       (integer&&!Number.isInteger(value))||(['skill','ultimate','echo','approach'].includes(kind)&&interval<.2))throw new Error('模块参数错误');
    if(kind==='idle_attack') { if(idleSlots.has(slot))throw new Error('同一角色有多个空闲普攻'); idleSlots.add(slot); }
    modules.push([kind,slot,value,interval]);
  }
  if(offset!==raw.length)throw new Error('种子含多余内容');
  const axis={name:originalName,order:ORDERS[order],times,modules};
  const id=createHash('sha256').update(JSON.stringify([name,axis])).digest('hex').slice(0,24);
  return {id,name,seed:seed.trim(),modules:count,order:ORDERS[order],times,axis};
}
