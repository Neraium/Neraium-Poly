// Fixed entry points avoid the vulnerable glob dependency chain entirely.
import { build, context } from 'esbuild';
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { basename } from 'node:path';
import http from 'node:http';
const dev = process.argv.includes('--dev');
const options = {
 entryPoints:['src/main.tsx'],bundle:true,format:'esm',target:'es2022',jsx:'automatic',
 outdir:'dist/assets',entryNames:'[name]-[hash]',metafile:true,minify:!dev,sourcemap:false,
 define:{'process.env.NODE_ENV':JSON.stringify(dev?'development':'production')},
 plugins:[{name:'html-entry',setup(b){b.onEnd(async result=>{
  if(result.errors.length)return;
  const entry=Object.entries(result.metafile.outputs).find(([,v])=>v.entryPoint==='src/main.tsx');
  if(!entry)throw Error('dashboard entry missing');
  let html=await readFile('index.html','utf8');
  html=html.replace('/src/main.tsx','/assets/'+basename(entry[0]));
  if(entry[1].cssBundle)html=html.replace('</head>','<link rel="stylesheet" href="/assets/'+basename(entry[1].cssBundle)+'"></head>');
  await mkdir('dist',{recursive:true});await writeFile('dist/index.html',html);
 });}}],
};
if(!dev)await build(options);
else {
 const ctx=await context(options);await ctx.rebuild();await ctx.watch();
 const upstream=await ctx.serve({host:'127.0.0.1',port:0,servedir:'dist'});
 // Development-only fixed loopback proxy; never accepts a caller-selected host.
 const server=http.createServer((req,res)=>{
  if(!req.url?.startsWith('/')||req.url.startsWith('//')){res.writeHead(400);res.end();return;}
  const proxy=http.request({hostname:'127.0.0.1',port:req.url.startsWith('/api/')?18740:upstream.port,path:req.url,method:req.method,headers:req.headers},response=>{
   res.writeHead(response.statusCode??502,response.headers);response.pipe(res);
  });
  proxy.setTimeout(10000,()=>proxy.destroy());
  proxy.on('error',()=>{if(!res.headersSent)res.writeHead(502);res.end();});
  req.on('aborted',()=>proxy.destroy());req.pipe(proxy);
 });
 server.listen(18741,'127.0.0.1');
 server.on('error',async error=>{console.error(error);await ctx.dispose();process.exitCode=1;});
 for(const sig of ['SIGINT','SIGTERM'])process.once(sig,()=>{server.close();ctx.dispose().then(()=>process.exit());});
}
