import {createReviewPacing} from './pacing.mjs'

export async function continueHistoricalReview({review,button,policy,read,click,pause}){
 if(policy.first){
  await read('firstReview',review.locator('.review-values,.review-method,.review-table-source,.review-source-page').first())
  await read('reviewChoice',review.getByRole('combobox',{name:'审核判断'}))
  await click(button)
  await read('reviewReceipt')
 }else{
  await pause(policy.readSeconds*1000);await button.click()
 }
}

// Each hold belongs to a meaningful screen. No chapter-end timing padding.
export function createScenes({page,b,base,task,click,choose,selectTab,read,pause,move,reveal,taskView,navData,settings,closeDrawer,steps}){
 const ebv='视线E(B−V)消光'
 const tab=(name)=>page.getByRole('tab',{name,exact:true})
 const latestCard=()=>page.locator(`.sample-card[data-sample-id="${task}"]`)
 const drawer=()=>page.locator('.context-drawer')
 async function loadedDrawer(){
  await drawer().waitFor({state:'visible'})
  await drawer().getByRole('status').filter({hasText:/正在读取|加载中/}).first().waitFor({state:'hidden'})
 }
 async function savedReading(scope){
  await scope.locator('.reading-analysis-sections,.workbench-material-summary').first().waitFor({state:'visible'})
 }
 async function changeSlider(slider,value){
  await reveal(slider)
  const box=await slider.boundingBox()
  const min=Number(await slider.getAttribute('min')),max=Number(await slider.getAttribute('max'))
  const thumbInset=8,toX=v=>box.x+thumbInset+(box.width-thumbInset*2)*(v-min)/(max-min)
  await move(toX(Number(await slider.inputValue())),box.y+box.height/2)
  await page.mouse.down();await move(toX(value),box.y+box.height/2,{drag:true});await page.mouse.up()
  // Exact keyboard adjustment uses the same component handler, without a JS mutation.
  await slider.focus()
  const step=Number(await slider.getAttribute('step'))||.1
  for(let i=0;i<3&&Math.abs(Number(await slider.inputValue())-value)>step/2;i++)await slider.press(Number(await slider.inputValue())<value?'ArrowRight':'ArrowLeft')
 }
 return {
  async home(){
   await b('检索与对话选项').waitFor()
   await read('input')
   await click(b('检索与对话选项'));await read('options');await click(b('检索与对话选项'))
  },
  async gallery(){
   await click(b('演示样例'));await latestCard().waitFor()
   await read('sample',latestCard().getByRole('button',{name:'回放过程',exact:true}))
  },
  async replay(){
   if(!await latestCard().isVisible()){
    if(!await b('演示样例').isVisible())await page.goto(base)
    await click(b('演示样例'));await latestCard().waitFor()
   }
   await click(latestCard().getByRole('button',{name:'回放过程',exact:true}))
   await choose(page.getByRole('combobox',{name:'播放速度',exact:true}),'100')
   const pacing=createReviewPacing(),start=Date.now();let reported=0
   while(Date.now()-start<1800000){
    const button=b('提交并继续回放')
    if(await button.isVisible()){
     const review=page.locator('[data-replay-gate]').filter({has:button}).first()
     const key=await review.getAttribute('data-replay-gate'),policy=pacing.claim(key)
     if(policy){
      await continueHistoricalReview({review,button,policy,read,click,pause})
      steps.push({review_key:key,first:pacing.count===1,reused_original_answer:true})
     }
    }
    if(await b('再次播放').isVisible())break
    if(Date.now()-reported>15000){console.log('REPLAY',await page.locator('.player-time-badge').innerText(),'unique reviews',pacing.count);reported=Date.now()}
    await page.waitForTimeout(180)
   }
   if(!await b('再次播放').isVisible())throw Error('Normal 100× replay did not finish')
   steps.push({replay_gates:pacing.count,normal_speed:100,no_seek:true})
   await read('complete')
   // One exit and one final-result entry. Avoid opening a read-only final view
   // and immediately backing out of the very same result as in V1.
   await click(b('返回'));await latestCard().waitFor()
   await click(latestCard().getByRole('button',{name:'查看成果',exact:true}))
  },
  async execution(){
   await taskView('执行明细')
   await selectTab(tab('执行全景'))
   const node=page.locator('.execution-chart .execution-visit').first();await node.waitFor()
   await read('overview');await click(node);await read('node')
   await selectTab(tab('异常与事件'));await read('events')
   await selectTab(tab('作业明细'));await read('jobs')
  },
  async data(){
   await navData('数据');await selectTab(b('测量记录'))
   const selection=page.getByRole('checkbox',{name:'选择本页测量',exact:true})
   await selection.waitFor();await read('overview')
   await choose(page.getByRole('combobox',{name:'按性质筛选',exact:true}),{label:ebv})
   await page.getByText(/当前筛选：\s*55\s*\/\s*960/).waitFor()
   await read('filtered',selection)
   if(!await selection.isChecked())await click(selection)
   await read('selection');if(await selection.isChecked())await click(selection)
   await selectTab(b('研究图像'))
   const image=page.locator('.figure-image-container').first();await image.waitFor();await read('images',image)
   await click(image);await loadedDrawer();await read('image');await closeDrawer()
  },
  async material(){
   await navData('资料')
   const search=page.getByRole('searchbox',{name:'搜索资料',exact:true})
   if(await search.inputValue()!=='Swift Ultraviolet'){await click(search);await search.fill('');await search.pressSequentially('Swift Ultraviolet',{delay:25})}
   const card=page.locator('.grouped-material-card').filter({hasText:'Swift Ultraviolet'}).first()
   await card.waitFor();await read('directory',card.locator('button').first())
   const opener=card.getByRole('button').filter({hasText:/查看|阅读|资料/}).first()
   await click(await opener.count()?opener:card.getByRole('button').first())
   await b('本篇解读').waitFor()
   // Keep the same physical property from the data filter through the paper,
   // cross-source report and follow-up, rather than changing topic at each tab.
   const property=page.getByRole('button',{name:/视线E.*消光/}).filter({visible:true}).first()
   await selectTab(property)
   await read('identity',page.locator('.material-reading-header h2'))
   const main=page.locator('.material-reading-page .reading-main')
   await reveal(main.getByRole('heading',{name:'本篇解读',exact:true}))
   await savedReading(main)
   await read('main',main.locator('.reading-analysis-section,.workbench-material-summary').first().locator('h4,h3').first())
   const advice=main.locator('.reading-advice');await read('advice',advice.getByRole('heading',{name:'理解与使用提示',exact:true}))
   const citation=advice.locator('.reading-tip .reading-citation').filter({hasText:'知识：'}).first()
   if(await citation.count()){
    await click(citation);await loadedDrawer();await read('citation');await closeDrawer()
   }else{
    // Some saved materials cite only their original records, not knowledge.
    // Keep that provenance honest; never substitute a background-only link.
    const original=advice.locator('.reading-citation').first()
    if(await original.count()){await click(original);await loadedDrawer();await read('citation');await closeDrawer()}
   }
   await selectTab(b('测量与图像'))
   const attachments=page.getByRole('navigation',{name:'本资料产出分类'}).getByRole('button',{name:/官方附表/})
   if(await attachments.isVisible()&&!/官方附表\s*0$/.test(await attachments.innerText()))await selectTab(attachments)
   await read('records',page.locator('#reading-data h3').first())
   await selectTab(b('原文与来源'));await read('source',page.locator('#reading-sources h3').first())
  },
  async comparison(){
   await navData('性质对照')
   await choose(page.getByRole('combobox',{name:'对照性质',exact:true}),{label:ebv})
   await selectTab(b('综合解读'))
   const comparison=page.locator('.property-comparison-page');await savedReading(comparison)
   await read('summary',comparison.locator('.property-comparison-heading'))
   await selectTab(b('来源对照'));await comparison.locator('table tbody tr').first().waitFor()
   await read('sources',comparison.locator('table thead'))
  },
  async quality(){
   await navData('质量与处理')
   await page.locator('.research-score-overview').waitFor();await read('overview')
   await selectTab(b('处理记录'))
   await page.getByText('正在读取处理溯源…',{exact:true}).waitFor({state:'hidden'})
   await page.locator('.trace-operation-card,.research-timeline,.trace-empty-box').filter({visible:true}).first().waitFor()
   await read('processing')
   await selectTab(b('覆盖与差异'))
   await page.getByRole('status').filter({hasText:/正在读取.*(?:对照|覆盖)/}).first().waitFor({state:'hidden'})
   await page.locator('.archive-groups-section,.coverage-matrix').filter({visible:true}).first().waitFor()
   await read('coverage')
  },
  async followup(){
   // Go straight from the current result to chat, with no data-tab detour.
   await taskView('对话')
   const turn=page.locator('.research-turn').last();await turn.waitFor()
   await read('question',turn.locator('.research-user-message'))
   await read('table',turn.locator('[data-block-type="table"]'))
   const plot=turn.locator('[data-block-type="chart"]');await read('chart',plot)
   const canvas=plot.locator('canvas').first();if(await canvas.isVisible()){const box=await canvas.boundingBox();await move(box.x+box.width*.42,box.y+box.height*.45);await pause(550)}
   await click(plot.locator('.research-block-refs button').first());await loadedDrawer();await read('record');await closeDrawer()
   const formula=turn.locator('[data-block-type="formula"]')
   await click(formula.locator('.research-block-refs button').first());await loadedDrawer();await read('knowledge');await closeDrawer()
   await read('formula',formula)
   const explore=turn.locator('[data-block-type="explore"]'),slider=explore.getByRole('slider')
   await reveal(explore,{block:'start',force:true});await changeSlider(slider,1.8);await read('trialLow')
   await changeSlider(slider,4.2);await read('trialHigh')
   await changeSlider(slider,3.1);await read('trialRestore')
  },
  async knowledge(){
   await settings();await click(b('知识库与图谱'))
   await click(page.getByRole('button',{name:/打开.*工作台|配置工作台/}).first())
   await tab('图谱').waitFor();await selectTab(tab('图谱'))
   const category=page.locator('.kwb-taxonomy').getByRole('button',{name:/观测方法学/})
   await category.waitFor();await page.locator('.knowledge-workspace[aria-busy="false"]').waitFor();await read('overview')
   await click(category);await page.locator('.knowledge-workspace[aria-busy="false"]').waitFor();await read('category')
   await selectTab(tab('矩阵'))
   const search=page.getByRole('textbox',{name:'搜索理论知识',exact:true});await click(search);await search.fill('颜色 消光与衰减的含义')
   const title=page.locator('[data-entry-id="common.photometry.color_extinction"] .kr-title-button');await title.waitFor()
   await read('matrix',title);await click(title)
   await page.locator('.kr-drawer-backdrop').waitFor();await page.getByText('正在载入完整详情…',{exact:true}).waitFor({state:'hidden'});await read('detail')
  },
  async registry(){
   await settings();await click(b('天体与性质规范'));await click(b('打开规范工作台 →'))
   await selectTab(b('性质定义'));await page.locator('.rwb-records[aria-busy="false"]').waitFor()
   await read('graph');await selectTab(b('表格'))
   const record=page.locator('.rwb-record-link').first();await record.waitFor();await read('table',record);await click(record)
   await page.locator('.rwb-detail').waitFor();await read('detail')
  },
  async theme(){
   await settings();await click(b('外观与配色'));await read('before')
   const preset=page.getByRole('combobox',{name:'配色预设',exact:true}),previous=await preset.inputValue()
   const fields=page.locator('.theme-color-hex-input'),colors=await fields.evaluateAll(inputs=>inputs.map(el=>el.value))
   try{
    await choose(preset,previous==='deep-space-cobalt'?'classic-emerald':'deep-space-cobalt');await read('changed')
   }finally{
    if(previous==='custom'){for(let i=0;i<colors.length;i++)await fields.nth(i).fill(colors[i])}
    else await choose(preset,previous)
   }
   await read('restored')
  },
  async export(){
   await navData('数据');await selectTab(b('测量记录'))
   const selection=page.getByRole('checkbox',{name:'选择本页测量',exact:true});await selection.waitFor();if(!await selection.isChecked())await click(selection)
   await read('scope');await click(b('导出结果'));await page.getByRole('dialog').waitFor();await read('formats')
  }
 }
}
