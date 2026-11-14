import { getStore } from '@netlify/blobs';
import { readSeed, supportedActions } from '../../lib/seed-wire.mjs';

const normalize = value => value.normalize('NFKC').toLowerCase();
const encode = value => Buffer.from(value).toString('hex');
const response = (body,status=200) => Response.json(body,{status,headers:{'Cache-Control':'no-store'}});

export async function handle(request, store) {
  const url=new URL(request.url);
  try {
    if(request.method==='POST') {
      if(Number(request.headers.get('content-length')||0)>32768)return response({error:'上传内容过大'},413);
      const text=await request.text();
      if(Buffer.byteLength(text)>32768)return response({error:'上传内容过大'},413);
      const data=JSON.parse(text), parsed=readSeed(data.seed);
      const item={id:parsed.id,name:parsed.name,seed:parsed.seed,modules:parsed.modules,
                  order:parsed.order,times:parsed.times,created:new Date().toISOString()};
      const key='records/'+item.id;
      const created=await store.setJSON(key,item,{onlyIfNew:true});
      const record=created.modified?item:await store.get(key,{type:'json'});
      if(!record)throw new Error('保存未完成，请重新上传');
      // Immutable per-record indexes: no shared counters or concurrent updates.
      const nameKey=encode(normalize(record.name));
      await Promise.all([...new Set(Array.from(normalize(record.name)))].map(character =>
        store.setJSON(`index/${encode(character)}/${nameKey}/${record.id}`,record,{onlyIfNew:true})));
      return response({item:record,duplicate:!created.modified},created.modified?201:200);
    }
    if(request.method!=='GET')return response({error:'不支持该请求'},405);
    if(url.searchParams.has('health'))return response({ok:true,format:5,actions:supportedActions});
    const id=url.searchParams.get('id');
    if(id) {
      if(!/^[0-9a-f]{24}$/.test(id))return response({error:'种子编号无效'},400);
      const item=await store.get('records/'+id,{type:'json'});
      return item?response({item}):response({error:'未找到该种子'},404);
    }
    const query=normalize((url.searchParams.get('name')||'').trim());
    if(Array.from(query).length>10)return response({error:'名称最多10个字'},400);
    const prefix=query?`index/${encode(Array.from(query)[0])}/`:'records/';
    const records=[], seen=new Set();
    let scanned=0, truncated=false;
    for await (const page of store.list({prefix,paginate:true})) {
      const keys=[];
      for(const entry of page.blobs) {
        if(++scanned>5000) {truncated=true;break;}
        if(query) {
          const storedName=Buffer.from(entry.key.split('/')[2],'hex').toString('utf8');
          if(!storedName.includes(query))continue;
        }
        keys.push(entry.key);
      }
      // Read bounded batches, then select by upload time rather than blob-key
      // order. Old records remain visible without an index migration.
      for(let offset=0;offset<keys.length;offset+=20) {
        const batch=await Promise.all(keys.slice(offset,offset+20).map(key=>store.get(key,{type:'json'})));
        for(const item of batch) {
          if(item&&!seen.has(item.id)) {
            seen.add(item.id);
            const {seed,...summary}=item;
            records.push(summary);
          }
        }
        records.sort((a,b)=>b.created.localeCompare(a.created)||a.id.localeCompare(b.id));
        if(records.length>50) {records.length=50;truncated=true;}
      }
      if(scanned>5000)break;
    }
    return response({items:records,truncated});
  } catch(error) {
    if(error instanceof SyntaxError||/种子|模块|角色|驻场|名称|参数|格式/.test(error.message))return response({error:error.message},400);
    console.error('Seed library failed',error.message);
    return response({error:'种子库暂时不可用，请稍后重试'},503);
  }
}

export default async request => handle(request,getStore({name:'wwbs-public-seeds-v1',consistency:'strong'}));
export const config={method:['GET','POST'],rateLimit:{action:'rate_limit',aggregateBy:'ip',windowSize:60,windowLimit:60}};
