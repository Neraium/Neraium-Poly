"""CONTROLLED fixtures only; not market observations, forecasts, fills or P/L."""
import asyncio,datetime,importlib.util,json,pathlib,subprocess,sys,tempfile,time
from neraium_poly.experimental.config import ExperimentalConfig
from neraium_poly.experimental.runtime import ExperimentalRuntime
sys.path.insert(0,str(pathlib.Path('tests').resolve()))
from test_experimental_runtime import Clock,Feed,Fees
parent=pathlib.Path('data/phase34/CONTROLLED');parent.mkdir(parents=True,exist_ok=True)
base=pathlib.Path(tempfile.mkdtemp(prefix='replay-',dir=parent))
source=subprocess.check_output(['git','show','26ee812:backend/neraium_poly/experimental/runtime.py'],text=True);p=base/'baseline_runtime.py';p.write_text(source)
spec=importlib.util.spec_from_file_location('neraium_poly.experimental.controlled_phase34_baseline',p);module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
async def sample(cls,name,i):
 moment=datetime.datetime(2026,11,8,tzinfo=datetime.UTC);clock=Clock(moment);folder=base/f'{name}-{i}';config=ExperimentalConfig(data_dir=folder/'experimental',certified_directory=folder/'certified',max_tokens=2,min_free_disk_mb=512,fee_batch=0);r=cls(config,feed=Feed(clock),clock=clock,fee_adapter=Fees());append=r.events.append;advance=r.account.advance
 def slow_append(record):time.sleep(.02);return append(record)
 def slow_advance(*args,**kwargs):time.sleep(.08);return advance(*args,**kwargs)
 r.events.append=slow_append;r.account.advance=slow_advance;gaps=[];done=False
 async def ticker():
  last=time.monotonic()
  while not done:
   await asyncio.sleep(.005);now=time.monotonic();gaps.append(now-last);last=now
 pulse=asyncio.create_task(ticker());await asyncio.sleep(0);start=time.monotonic()
 try:
  await r.cycle();await asyncio.sleep(.01);done=True;await pulse
  assert r.account.snapshot(now=clock())['cash']==500 and not r.account.broker.history()
  return {'wall_seconds':time.monotonic()-start,'ticker_max_gap_seconds':max(gaps),'ticker_samples':len(gaps),'actual_orders':0,'fixture_cash':500}
 finally:done=True;await pulse;await r.close()
async def main():
 out={'scope':'three matched controlled fixture cycles per source; identical injected20ms durable-append and80ms reconcile delays; no authentic performance/trading evidence','baseline_commit':'26ee812','final_commit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'baseline':[],'final':[]}
 for i in range(3):
  out['baseline'].append(await sample(module.ExperimentalRuntime,'baseline',i));out['final'].append(await sample(ExperimentalRuntime,'final',i))
 (base/'controlled-io-comparison.json').write_text(json.dumps(out,indent=2)+'\n');print(out)
asyncio.run(main())
