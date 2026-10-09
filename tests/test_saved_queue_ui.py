"""Browser-level contracts for the local webview's saved queue controls.

The browser test runs when Node, Playwright and a Chromium browser are available.
Set NODE_PATH and PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH for custom installations.
"""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("saved_queue_ui", ROOT / "src/app_ui.py")
ui = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ui)


class SavedQueueUiTests(unittest.TestCase):
    def test_saved_queue_keeps_native_recovery_and_theme_controls(self):
        for element_id in ("queue-select", "queue-name-modal", "queue-save-state",
                           "add-text-btn", "retry-failed-btn", "clear-completed-btn",
                           "recovery-panel", "preferences-modal", "theme-select"):
            self.assertIn(f'id="{element_id}"', ui.HTML)
        self.assertIn('function renderSavedQueue(state)', ui.HTML)
        self.assertIn('function renderFolderQueue(items, state={})', ui.HTML)
        self.assertNotIn('window.prompt(', ui.HTML)

    def test_saved_queue_browser_behavior(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node is not installed")
        env = os.environ.copy()
        bundled = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules"
        if bundled.is_dir():
            env["NODE_PATH"] = os.pathsep.join(filter(None, [env.get("NODE_PATH"), str(bundled)]))
        probe = subprocess.run([node, "-e", "require('playwright')"], env=env, capture_output=True, text=True)
        if probe.returncode:
            self.skipTest("Playwright is not installed")
        if not env.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH"):
            chrome = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
            if chrome.exists():
                env["PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH"] = str(chrome)
        result = subprocess.run([node, "-e", BROWSER_TEST], env=env,
                                input=json.dumps({"html": ui.HTML}), capture_output=True,
                                text=True, timeout=90)
        if "Executable doesn't exist" in result.stderr:
            self.skipTest("A Playwright Chromium browser is not installed")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Queue browser checks passed", result.stdout)


BROWSER_TEST = r'''
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
(async () => {
 const {html} = JSON.parse(fs.readFileSync(0,'utf8'));
 const browser = await chromium.launch({headless:true, ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH ? {executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH} : {})});
 try {
  const page = await browser.newPage({viewport:{width:640,height:640}});
  const errors=[]; page.on('pageerror',error=>errors.push(error.message));
  await page.setContent(html);
  await page.evaluate(() => {
   window.testCalls=[];
   window.testQueue={active_id:'inbox',queues:[{id:'inbox',name:'Inbox'}],items:[],waiting:0,failed:0,done:0,total:0,busy:false,saved:true};
   window.resetQueue = changes => { window.testQueue={...window.testQueue,...changes}; renderSavedQueue(window.testQueue); };
   window.pywebview={api:new Proxy({}, {get:(_,name)=>async(...args)=>{window.testCalls.push([name,...args]); return window.testQueue;}})};
   renderApplicationState({queue:window.testQueue,vault_configured:false,recovery_jobs:[]});
  });
  assert.equal(await page.locator('#convert-btn').isDisabled(),true);
  assert.equal(await page.locator('#queue-save-state').textContent(),'Saved');
  assert.equal(await page.getByLabel('Include subfolders',{exact:true}).count(),1,'Folder depth must be an explicit choice beside Add folder');
  const folderChoice = page.getByLabel('Include subfolders',{exact:true});
  assert.equal(await folderChoice.isChecked(),true,'Existing recursive behavior stays the default');
  await page.evaluate(()=>{
   window.testPrefs={theme:'system',raw_ocr_mode:'different',output_dir:null,auto_open_output:false,include_subfolders:true};
   window.pywebview.api={set_include_subfolders:async(value)=>{
    window.testCalls.push(['set_include_subfolders',value]);
    return await new Promise(resolve=>window.finishFolderChoice=()=>resolve({...window.testPrefs,include_subfolders:value}));
   }};
  });
  await folderChoice.uncheck();
  assert.equal(await folderChoice.isDisabled(),true,'Do not offer another choice before this one is saved');
  assert.equal(await page.locator('#add-folder-btn').isDisabled(),true,'Folder intake waits for the saved choice');
  await page.evaluate(()=>document.getElementById('add-folder-btn').click());
  assert.deepEqual(await page.evaluate(()=>window.testCalls),[['set_include_subfolders',false]]);
  await page.evaluate(()=>window.finishFolderChoice());
  await page.waitForFunction(()=>!document.getElementById('include-subfolders-cb').disabled);
  assert.equal(await folderChoice.isChecked(),false);
  await page.locator('#preferences-btn').click();
  await page.locator('#preferences-cancel-btn').click();
  assert.equal(await folderChoice.isChecked(),false,'Preferences must preserve the saved folder choice');
  await page.evaluate(()=>{window.pywebview.api={set_include_subfolders:async()=>{throw Error('Storage is read-only');}};});
  await folderChoice.click();
  await page.waitForFunction(()=>!document.getElementById('include-subfolders-cb').checked);
  assert.equal(await folderChoice.isEnabled(),true,'A failed save must release the control');
  assert.match(await page.locator('#toast').textContent(),/Could not save folder choice.*Storage is read-only/);
  await page.evaluate(()=>{
   applyPreferences({...window.testPrefs,include_subfolders:true});
   window.testCalls=[];
   window.pywebview.api=new Proxy({}, {get:(_,name)=>async(...args)=>{window.testCalls.push([name,...args]);return window.testQueue;}});
  });
  assert.equal(await page.getByText('Saved queues',{exact:true}).isVisible(),true);
  assert.equal(await page.getByLabel('Saved queues',{exact:true}).getAttribute('id'),'queue-select');
  assert.equal(await page.locator('#delete-saved-queue-btn').isVisible(),true,'Whole-queue deletion must be visible beside the queue name');
  assert.equal(await page.locator('#delete-saved-queue-btn').isEnabled(),true,'An empty queue must be deletable');
  // Safari does not focus buttons on mouse clicks. Preserve the opening
  // control even when document.activeElement is still the page body.
  await page.evaluate(()=>document.getElementById('delete-saved-queue-btn').click());
  assert.equal(await page.locator('#queue-delete-title').textContent(),'Delete “Inbox”?');
  assert.equal(await page.evaluate(()=>document.activeElement.id),'queue-delete-cancel-btn');
  await page.locator('#queue-delete-cancel-btn').click();
  await page.waitForFunction(()=>document.activeElement.id==='delete-saved-queue-btn');
  assert.equal(await page.evaluate(()=>window.testCalls.length),0,'Opening and canceling the confirmation must not remove anything');
  await page.locator('#text-tab').click();
  await page.locator('#url-input').fill('https://example.com/one\nhttps://example.com/two');
  assert.equal(await page.locator('#convert-btn').isDisabled(),true,'Unstaged text must not enable conversion');
  await page.locator('#add-text-btn').click();
  assert.deepEqual(await page.evaluate(()=>window.testCalls.pop()),['stage_text','https://example.com/one\nhttps://example.com/two']);
  assert.equal(await page.locator('#url-input').inputValue(),'');

  await page.evaluate(()=>resetQueue({items:[{id:'missing',kind:'file',title:'<img src=x onerror=alert(1)>.pdf',source:'/tmp/missing.pdf',status:'failed',error:'File moved. Locate it to continue.'},{id:'done',kind:'url',title:'Website',source:'https://example.com',status:'done',output_path:'/tmp/example.md'}],waiting:0,failed:1,done:1,total:2}));
  assert.equal(await page.locator('#folder-queue img').count(),0,'Names must render as text');
  assert.equal(await page.locator('.queue-status.failed').textContent(),'Failed');
  assert.equal(await page.locator('.queue-error').textContent(),'File moved. Locate it to continue.');
  assert.equal(await page.locator('.queue-locate-btn').count(),1);
  await page.locator('.queue-locate-btn').click();
  assert.deepEqual(await page.evaluate(()=>window.testCalls.pop()),['locate_queue_item','missing']);
  assert.equal(await page.locator('#convert-btn').isDisabled(),true,'Failed and completed items are not waiting');
  assert.equal(await page.locator('#retry-failed-btn').isEnabled(),true);

  await page.evaluate(()=>{window.pywebview.api={retry_failed:async()=>{throw Error('Cannot start retry');}};});
  await page.locator('#retry-failed-btn').click();
  assert.equal(await page.locator('#new-queue-btn').isEnabled(),true,'Rejected conversion must release busy state');
  assert.equal(await page.locator('#toast').textContent(),'Cannot start retry');
  await page.locator('#queue-tab').click();
  await page.evaluate(()=>resetQueue({waiting:1,failed:1,total:3}));
  await page.locator('#url-input').fill('This draft is not staged');
  await page.evaluate(()=>{window.pywebview.api={convert_staged:async()=>{window.testCalls.push(['convert_staged']);return false;}};});
  await page.locator('#convert-btn').click();
  assert.deepEqual(await page.evaluate(()=>window.testCalls.pop()),['convert_staged'],'Text mode must convert the saved queue');
  assert.equal(await page.locator('#url-input').inputValue(),'This draft is not staged');
  assert.equal(await page.locator('#convert-btn').isEnabled(),true);
  await page.locator('#queue-tab').click();

  await page.evaluate(()=>{window.pywebview.api={create_queue:async(name)=>{window.testCalls.push(['create_queue',name]);return {...window.testQueue,active_id:'new',queues:[...window.testQueue.queues,{id:'new',name}]};}};});
  await page.locator('#new-queue-btn').click();
  assert.equal(await page.evaluate(()=>document.activeElement.id),'queue-name-input');
  await page.locator('#queue-name-input').fill('  Research links  ');
  await page.locator('#queue-name-input').press('Enter');
  await page.waitForFunction(()=>!document.getElementById('queue-name-modal').open);
  assert.deepEqual(await page.evaluate(()=>window.testCalls.pop()),['create_queue','Research links']);
  assert.equal(await page.locator('#queue-select').inputValue(),'new');
  assert.equal(await page.evaluate(()=>document.activeElement.id),'new-queue-btn');
  await page.locator('#rename-queue-btn').click();
  assert.equal(await page.locator('#queue-name-input').inputValue(),'Research links');
  await page.locator('#queue-name-input').press('Escape');
  assert.equal(await page.evaluate(()=>document.activeElement.id),'rename-queue-btn');

  await page.evaluate(()=>{window.pywebview.api={stage_drop:async(payload)=>{window.testCalls.push(['stage_drop',payload]);return window.testQueue;}};});
  await page.evaluate(()=>{const dt=new DataTransfer(); dt.setData('text/uri-list','# Link\r\nhttps://example.com/page');dt.setData('text/plain','https://example.com/page');document.dispatchEvent(new DragEvent('drop',{dataTransfer:dt,bubbles:true,cancelable:true}));});
  assert.deepEqual(await page.evaluate(()=>window.testCalls.pop()),['stage_drop',{text:'',urls:['https://example.com/page'],files:[]}]);
  await page.evaluate(()=>{const dt=new DataTransfer();dt.items.add(new File(['hello'],'source.txt',{type:'text/plain'}));dt.setData('text/plain','file:///tmp/source.txt');document.dispatchEvent(new DragEvent('drop',{dataTransfer:dt,bubbles:true,cancelable:true}));});
  assert.equal(await page.evaluate(()=>window.testCalls.filter(call=>call[0]==='stage_drop').length),0,'Native files must not be staged twice');

  await page.evaluate(()=>resetQueue({saved:false,save_error:'Could not save this queue'}));
  assert.equal(await page.locator('#queue-save-state').textContent(),'Not saved');
  assert.equal(await page.locator('#toast').textContent(),'Could not save this queue');
  await page.evaluate(()=>{window.pywebview.api={stage_text:async()=>{throw Error('Queue storage unavailable');}};});
  await page.locator('#add-text-btn').click();
  assert.equal(await page.locator('#add-text-btn').isEnabled(),true);
  assert.equal(await page.locator('#url-input').inputValue(),'This draft is not staged','Failed staging must preserve the draft');
  assert.equal(await page.locator('#queue-save-state').textContent(),'Not saved');
  await page.evaluate(()=>resetQueue({saved:true,save_error:'',busy:true}));
  assert.equal(await page.locator('.folder-remove-btn').first().isDisabled(),true);
  assert.equal(await page.locator('.queue-locate-btn').isDisabled(),true);
  assert.equal(await page.locator('#queue-select').isDisabled(),true);
  assert.equal(await page.locator('#delete-saved-queue-btn').isDisabled(),true);
  assert.equal(await folderChoice.isDisabled(),true,'Keep folder depth fixed during conversion');
  await page.evaluate(()=>resetQueue({busy:false}));

  await page.locator('#queue-actions-btn').click();
  assert.equal(await page.evaluate(()=>document.activeElement.id),'clear-completed-btn');
  await page.locator('#clear-completed-btn').press('Escape');
  assert.equal(await page.locator('#queue-actions-menu').isHidden(),true);
  assert.equal(await page.evaluate(()=>document.activeElement.id),'queue-actions-btn');
  await page.evaluate(()=>{window.pywebview.api={create_queue:async()=>{throw Error('A collection with that name already exists');}};});
  await page.locator('#new-queue-btn').click();
  await page.locator('#queue-name-input').fill('Inbox');
  await page.locator('#queue-name-input').press('Enter');
  assert.equal(await page.locator('#queue-name-error').textContent(),'A collection with that name already exists');
  assert.equal(await page.locator('#queue-name-modal').isVisible(),true,'Rejected names stay editable with an inline error');
  await page.locator('#queue-name-input').press('Escape');

  await page.evaluate(()=>{
   renderSavedQueue({active_id:null,queues:[],items:[],total:0,waiting:0,failed:0,done:0,busy:false,saved:false,save_error:'Could not open saved queues: storage is read-only.'});
   document.getElementById('toast').hidden=true;
   renderRecoveryJobs([{id:'recovery',name:'Saved image batch',saved:10,pending:5,failed:0}]);
  });
  assert.equal(await page.locator('#queue-empty-title').textContent(),'Saved queues need attention');
  assert.equal(await page.locator('#queue-empty-copy').textContent(),'Could not open saved queues: storage is read-only.');
  for(const id of ['add-files-btn','add-folder-btn','include-subfolders-cb','drop-zone','url-input','add-text-btn','new-queue-btn','queue-select','delete-saved-queue-btn','convert-btn']) assert.equal(await page.locator('#'+id).isDisabled(),true,id+' must not offer unavailable queue intake');
  assert.equal(await page.locator('#preferences-btn').isEnabled(),true);
  assert.equal(await page.locator('.recovery-row button').isEnabled(),true,'Legacy recovery stays available');
  await page.evaluate(()=>{resetQueue({saved:false,save_error:'The last edit could not be saved'});renderRecoveryJobs([]);});
  assert.equal(await page.locator('#add-files-btn').isEnabled(),true,'An error on an existing queue does not disable intake');

  await page.evaluate(()=>resetQueue({saved:true,save_error:'',done:2,failed:0,waiting:0,total:2}));
  assert.equal(await page.locator('#progress-label').textContent(),'100%');
  await page.evaluate(()=>resetQueue({waiting:4,total:6}));
  assert.equal(await page.locator('#progress-label').textContent(),'33%','New waiting items must lower idle queue progress');
  await page.evaluate(()=>resetQueue({active_id:'empty',queues:[{id:'empty',name:'Empty'}],items:[],done:0,waiting:0,total:0}));
  assert.equal(await page.locator('#progress-label').textContent(),'0%');

  assert.equal(await page.locator('#queue-actions-btn').isEnabled(),true,'Empty queues can still be deleted');
  await page.locator('#queue-actions-btn').click();
  assert.equal(await page.locator('#clear-folders-btn').isDisabled(),true);
  await page.locator('#delete-queue-btn').click();
  assert.equal(await page.locator('#queue-delete-title').textContent(),'Delete “Empty”?');
  assert.match(await page.locator('#queue-delete-copy').textContent(),/empty Inbox/);
  assert.equal(await page.evaluate(()=>document.activeElement.id),'queue-delete-cancel-btn');
  await page.locator('#queue-delete-cancel-btn').click();
  assert.equal(await page.locator('#queue-delete-modal').isVisible(),false);
  assert.equal(await page.evaluate(()=>window.testCalls.filter(call=>call[0]==='delete_queue').length),0,'Cancel must preserve the queue');
  await page.waitForFunction(()=>document.activeElement.id==='queue-actions-btn');

  await page.evaluate(()=>{
   window.pywebview.api={delete_queue:async(id)=>{window.testCalls.push(['delete_queue',id]);throw Error('Storage is read-only');}};
  });
  await page.locator('#queue-actions-btn').click();
  await page.locator('#delete-queue-btn').click();
  await page.locator('#queue-delete-confirm-btn').click();
  assert.equal(await page.locator('#queue-delete-error').textContent(),'Storage is read-only');
  assert.equal(await page.locator('#queue-delete-modal').isVisible(),true,'Failed deletion stays visible with an inline error');
  assert.deepEqual(await page.evaluate(()=>window.testCalls.pop()),['delete_queue','empty']);
  await page.locator('#queue-delete-cancel-btn').press('Escape');

  await page.evaluate(()=>{
   resetQueue({active_id:'remove',queues:[{id:'remove',name:'<img src=x onerror=alert(1)>'},{id:'keep',name:'Reading list'}]});
   window.pywebview.api={delete_queue:async(id)=>{window.testCalls.push(['delete_queue',id]);return {...window.testQueue,active_id:'keep',queues:[{id:'keep',name:'Reading list'}]};}};
  });
  await page.locator('#queue-actions-btn').click();
  await page.locator('#delete-queue-btn').click();
  assert.equal(await page.locator('#queue-delete-modal img').count(),0,'Queue names render safely in confirmation');
  await page.evaluate(()=>resetQueue({active_id:'keep'}));
  await page.locator('#queue-delete-confirm-btn').click();
  await page.waitForFunction(()=>!document.getElementById('queue-delete-modal').open);
  assert.deepEqual(await page.evaluate(()=>window.testCalls.pop()),['delete_queue','remove'],'Confirmation retains the ID that was shown');
  assert.equal(await page.locator('#queue-select').inputValue(),'keep');

  await page.evaluate(()=>{
   resetQueue({active_id:'one',queues:[{id:'one',name:'Notes'},{id:'two',name:'Websites'}]});
   window.pywebview.api={select_queue:async(id)=>{window.testCalls.push(['select_queue',id]);return {...window.testQueue,active_id:id,items:[{id:'site',kind:'url',source:'https://example.com',title:'Example website',status:'waiting'}],waiting:1,total:1};}};
  });
  await page.getByLabel('Saved queues',{exact:true}).selectOption({label:'Websites'});
  assert.deepEqual(await page.evaluate(()=>window.testCalls.pop()),['select_queue','two']);
  assert.equal(await page.locator('.queue-name').textContent(),'Example website','Choosing a named queue restores its entries');

  await page.evaluate(()=>{
   window.largeQueue={active_id:'large',queues:[{id:'large',name:'Large queue'}],items:Array.from({length:5000},(_,i)=>({id:String(i),kind:'file',title:`Document ${i}.pdf`,source:`/tmp/research/Document ${i}.pdf`,group_name:'/tmp/research',status:'waiting'})),waiting:5000,failed:0,done:0,total:5000,busy:false,saved:true};
   renderSavedQueue(window.largeQueue);
  });
  assert.equal(await page.locator('#queue-count').textContent(),'5000');
  assert.equal(await page.locator('#folder-queue .queue-row').count(),200,'Large queues must bound the DOM');
  assert.equal(await page.locator('#queue-prev-btn').isDisabled(),true);
  assert.equal(await page.locator('#queue-pagination').isVisible(),true);
  for(let pageNumber=1;pageNumber<25;pageNumber++) await page.locator('#queue-next-btn').click();
  assert.equal(await page.locator('#folder-queue .queue-row').first().getAttribute('data-item-id'),'4800');
  assert.equal(await page.locator('#folder-queue .queue-row').last().getAttribute('data-item-id'),'4999');
  assert.equal(await page.locator('#queue-next-btn').isDisabled(),true);
  await page.locator('#queue-prev-btn').click();
  assert.equal(await page.locator('#folder-queue .queue-row').first().getAttribute('data-item-id'),'4600');
  await page.evaluate(()=>renderSavedQueue({...window.largeQueue,busy:true}));
  assert.equal(await page.locator('#folder-queue .queue-row').first().getAttribute('data-item-id'),'4600','Status updates preserve the current page');
  await page.evaluate(()=>renderSavedQueue({...window.largeQueue,busy:false}));
  await page.locator('#activity-tab').click();
  assert.equal(await page.locator('#queue-pagination').isHidden(),true);
  await page.locator('#queue-tab').click();
  const toolbarBounds=await page.evaluate(()=>{const toolbar=document.querySelector('.workspace-toolbar').getBoundingClientRect();return [...document.querySelectorAll('.workspace-toolbar > :not([hidden])')].map(element=>({left:element.getBoundingClientRect().left,right:element.getBoundingClientRect().right,top:element.getBoundingClientRect().top,bottom:element.getBoundingClientRect().bottom,toolbarLeft:toolbar.left,toolbarRight:toolbar.right,toolbarTop:toolbar.top,toolbarBottom:toolbar.bottom}));});
  for(const bounds of toolbarBounds) {assert.ok(bounds.left>=bounds.toolbarLeft && bounds.right<=bounds.toolbarRight,'Pagination must fit the minimum-width toolbar');assert.ok(bounds.top>=bounds.toolbarTop && bounds.bottom<=bounds.toolbarBottom,'Pagination must not wrap outside the toolbar');}
  const pickerBounds=await page.evaluate(()=>{const controls=document.querySelector('.queue-picker-controls').getBoundingClientRect();return [...document.querySelectorAll('.queue-picker-controls > *')].map(element=>({left:element.getBoundingClientRect().left,right:element.getBoundingClientRect().right,top:element.getBoundingClientRect().top,bottom:element.getBoundingClientRect().bottom,controlsLeft:controls.left,controlsRight:controls.right,controlsTop:controls.top,controlsBottom:controls.bottom}));});
  for(const bounds of pickerBounds) {assert.ok(bounds.left>=bounds.controlsLeft && bounds.right<=bounds.controlsRight,'Saved queue controls must fit the minimum-width toolbar');assert.ok(bounds.top>=bounds.controlsTop && bounds.bottom<=bounds.controlsBottom,'Saved queue controls must stay aligned');}
  await page.locator('#files-tab').click();
  const intakeBounds=await page.evaluate(()=>{const toolbar=document.querySelector('#files-source .input-toolbar').getBoundingClientRect();return [...document.querySelectorAll('#files-source .input-toolbar > *')].map(element=>({left:element.getBoundingClientRect().left,right:element.getBoundingClientRect().right,top:element.getBoundingClientRect().top,bottom:element.getBoundingClientRect().bottom,toolbarLeft:toolbar.left,toolbarRight:toolbar.right,toolbarTop:toolbar.top,toolbarBottom:toolbar.bottom}));});
  for(const bounds of intakeBounds) {assert.ok(bounds.left>=bounds.toolbarLeft && bounds.right<=bounds.toolbarRight,'Folder depth must fit the minimum-width toolbar');assert.ok(bounds.top>=bounds.toolbarTop && bounds.bottom<=bounds.toolbarBottom,'Folder intake controls must stay aligned');}
  await page.evaluate(()=>renderSavedQueue({...window.largeQueue,active_id:'other',queues:[{id:'other',name:'Other'}]}));
  assert.equal(await page.locator('#folder-queue .queue-row').first().getAttribute('data-item-id'),'0','Switching queues resets pagination');
  await page.evaluate(()=>renderSavedQueue({...window.largeQueue,items:window.largeQueue.items.slice(0,200),total:200,waiting:200}));
  assert.equal(await page.locator('#queue-pagination').isHidden(),true);
  await page.evaluate(()=>renderSavedQueue({...window.largeQueue,items:[{id:'url',kind:'url',title:'https://example.com',source:'https://example.com',status:'waiting'},{id:'webloc',kind:'url',title:'Useful article',source:'https://example.com/article',status:'waiting'}],total:2,waiting:2}));
  assert.equal(await page.locator('.queue-meta').first().textContent(),'Website · Fetched when you convert');
  assert.equal(await page.locator('.queue-meta').last().textContent(),'https://example.com/article','Meaningful web link titles retain their source URL');
  for (const theme of ['light','dark']) {
   await page.evaluate(theme=>document.body.dataset.theme=theme,theme);
   const bounds=await page.evaluate(()=>({body:document.body.scrollWidth,width:innerWidth,footer:document.querySelector('footer').getBoundingClientRect().bottom,height:innerHeight}));
   assert.ok(bounds.body<=bounds.width,'Minimum width must not overflow');
   assert.ok(bounds.footer<=bounds.height,'Footer controls must remain visible at the minimum window size');
  }
  assert.deepEqual(errors,[]);
  console.log('Queue browser checks passed');
 } finally { await browser.close(); }
})().catch(error=>{console.error(error);process.exitCode=1;});
'''


if __name__ == '__main__':
    unittest.main()
