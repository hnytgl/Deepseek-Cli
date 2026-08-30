(function(){
'use strict';
var $=function(s){return document.querySelector(s)}, $$=function(s){return Array.prototype.slice.call(document.querySelectorAll(s))};
var STORE='sproutspeak_apk_state_v4';
var LEGACY='sproutspeak_apk_state_v3';
var levels={
  prea1:{name:'Pre-A1 启蒙',target:'建立开口习惯，掌握高频生活词和最基本完整句。',prompt:'Use very short beginner English. Ask one concrete question at a time. Encourage 1 short complete sentence.'},
  a1:{name:'A1 基础',target:'能用简单完整句描述自己、喜好、日常活动和简单过去经历。',prompt:'Use simple A1 English. Encourage 1-2 complete sentences and basic and/because.'},
  ket:{name:'A2 Key / KET',target:'达到 KET 口语训练要求：完整回答、给理由、互动提问。',prompt:'Use A2 Key level English. Encourage 2-3 information points, reasons, past/future experiences and follow-up questions.'},
  b1:{name:'B1 PET',target:'形成更长的连贯表达，能比较、解释观点并自然追问。',prompt:'Use B1 everyday English. Ask for opinions, comparisons, reasons and connected answers.'}
};
var defaultState={
  child:{name:'Mia',age:9,interest:'food',level:'a1'},
  placementDone:false,placementDate:null,manualLevel:false,
  scores:{f:50,v:50,g:50,i:50},stats:{answers:0,sessions:0,minutes:0,streak:1,stars:20,lastDay:null},
  daily:{},history:[],aiSummary:''
};
var state=loadState();
var chatHistory=[],chatTurns=0,live=false,lastConfidence=-1,pending={},requestSeq=0;
var assessmentAnswers=[],assessmentIndex=0,assessmentMode='placement';
var activeTask=null,activeTaskStartTurns=0;
var currentConversationType='scene';
var nativeSpeechTarget='chat';

var scenes={
 shop:{title:'Ice Cream Shop',open:'Hello! Welcome to my ice cream shop. What would you like today?',goal:'礼貌点餐、口味、数量和理由',quick:["I'd like chocolate, please.","Can I have vanilla?","I want strawberry because it's sweet."]},
 zoo:{title:'At the Zoo',open:'Hi! Which animal would you like to see first, and why?',goal:'动物、偏好和理由',quick:['I want to see the lions.','I like pandas because they are cute.','Can we see the elephants next?']},
 school:{title:'New Classmate',open:"Hi! I'm Leo. What do you like doing after school?",goal:'自我介绍、兴趣和主动提问',quick:['I like drawing after school.','I play badminton with my friends.','What do you like doing?']},
 restaurant:{title:'At a Restaurant',open:'Good evening! What would you like to eat and drink?',goal:'点餐、礼貌表达和补充细节',quick:["I'd like noodles, please.",'Can I have some water?','I want rice because I am hungry.']},
 airport:{title:'At the Airport',open:'Hello! Where do you need to go? I can help you.',goal:'问路、理解指令和礼貌互动',quick:['Where is Gate 12?','Can you help me, please?','I am looking for my boarding gate.']},
 weekend:{title:'Weekend Plans',open:'Hi! What would you like to do this weekend, and why?',goal:'计划、偏好、理由和互动',quick:['I want to go cycling.','I like the cinema because it is fun.','What are you doing this weekend?']}
};
var placementQuestions=[
 {q:'What is your name, and what do you like?',hint:'先从简单问题开始。尽量用完整句回答。',sample:'My name is Mia. I like drawing and cats.'},
 {q:'What do you usually do after school?',hint:'说日常习惯，可以使用 usually / often / then。',sample:'I usually do my homework after school. Then I play badminton with my friend.'},
 {q:'Tell me about last weekend. What did you do?',hint:'尝试说过去发生的事情，并补充一个细节。',sample:'Last weekend I went to the park with my family. We rode bikes and had ice cream.'},
 {q:'Which is better for a fun day: swimming or going to the cinema? Why?',hint:'表达选择并给出理由，最好说 2 句。',sample:'I think swimming is better because it is healthy. I can also play with my friends.'},
 {q:'Do you prefer learning alone or with friends? Give your reasons, then ask me one question.',hint:'最后一题更有挑战：表达观点、给理由，再主动问老师一个问题。',sample:'I prefer learning with friends because we can help each other, but I study alone when I need to focus. What do you prefer?'}
];
var reassessQuestions={
 prea1:[
  {q:'What food do you like?',hint:'用完整句回答。',sample:'I like apples and noodles.'},
  {q:'What can you do?',hint:'用 I can... 说两件事。',sample:'I can swim and ride a bike.'},
  {q:'Tell me about your family in two simple sentences.',hint:'不需要说真实姓名。',sample:'I have a small family. We like watching films together.'}
 ],
 a1:[
  {q:'What do you do after school?',hint:'尽量说两句。',sample:'I do my homework after school. Then I play badminton.'},
  {q:'What did you do yesterday?',hint:'尝试使用过去时。',sample:'Yesterday I visited my grandma and we cooked dinner.'},
  {q:'What is your favourite hobby and why?',hint:'使用 because。',sample:'My favourite hobby is drawing because it is relaxing.'}
 ],
 ket:[
  {q:'Tell me something about your free time.',hint:'像 KET Part 1 一样给 2–3 个信息点。',sample:'I often play badminton after school. I also like reading because it is relaxing.'},
  {q:'What did you do last weekend?',hint:'过去经历 + 一个细节。',sample:'Last weekend I visited my grandparents. We had lunch together and watched a film.'},
  {q:'Which is better: a picnic or going to a museum? Why?',hint:'像 Part 2 一样表达偏好并给理由。',sample:'I think a picnic is better because I can be outside with my friends. What do you think?'}
 ],
 b1:[
  {q:'Describe an activity you enjoy and explain why it is important to you.',hint:'尽量连贯说 3–4 句。',sample:'I enjoy badminton because it keeps me active. I play twice a week and it also helps me spend time with friends.'},
  {q:'Tell me about a memorable weekend and what you learned from it.',hint:'使用过去时和连接词。',sample:'Last month I went hiking with my family. Although it was tiring, I learned that I can keep going when something is difficult.'},
  {q:'Do you think children should have more free time? Give reasons and ask me a follow-up question.',hint:'观点 + 理由 + 主动提问。',sample:'Yes, I think children need more free time because hobbies are important and help us relax. What did you enjoy doing when you were younger?'}
 ]
};
function clone(o){return JSON.parse(JSON.stringify(o))}
function loadState(){
  try{var v=JSON.parse(localStorage.getItem(STORE));if(v)return merge(v)}catch(e){}
  try{var old=JSON.parse(localStorage.getItem(LEGACY));if(old){var n=merge(old);n.placementDone=false;n.placementDate=null;n.daily={};return n}}catch(e){}
  return clone(defaultState);
}
function merge(v){
  var s=Object.assign(clone(defaultState),v||{});
  s.child=Object.assign({},defaultState.child,(v&&v.child)||{});
  s.scores=Object.assign({},defaultState.scores,(v&&v.scores)||{});
  s.stats=Object.assign({},defaultState.stats,(v&&v.stats)||{});
  s.daily=(v&&v.daily)||{};s.history=(v&&v.history)||[];
  return s;
}
function save(){localStorage.setItem(STORE,JSON.stringify(state));renderAll()}
function clamp(n,min,max){min=min==null?0:min;max=max==null?100:max;return Math.max(min,Math.min(max,Math.round(n)))}
function toast(msg){var t=$('#toast');t.textContent=msg;t.classList.add('show');clearTimeout(t._timer);t._timer=setTimeout(function(){t.classList.remove('show')},2200)}
function todayKey(){var d=new Date();return d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0')}
function levelName(){return state.placementDone?levels[state.child.level].name:'待评估'}
function weakKey(){return Object.keys(state.scores).sort(function(a,b){return state.scores[a]-state.scores[b]})[0]}
function weakName(){return {f:'流利度',v:'词汇表达',g:'语法准确',i:'互动能力'}[weakKey()]}
function go(page){$$('.page').forEach(function(p){p.classList.toggle('on',p.id==='page-'+page)});$$('.tab').forEach(function(b){b.classList.toggle('on',b.dataset.page===page)});if(page==='plan')renderWeeklyPlan();if(page==='assess')prepareAssessment();window.scrollTo({top:0,behavior:'smooth'})}
$$('.tab').forEach(function(b){b.onclick=function(){go(b.dataset.page)}});
function ensureDay(){var k=todayKey();if(!state.daily[k])state.daily[k]={done:[],started:[],minutes:0};return state.daily[k]}
function updateStreak(){var k=todayKey();if(!state.stats.lastDay){state.stats.lastDay=k;return}if(state.stats.lastDay===k)return;var a=new Date(state.stats.lastDay+'T00:00:00'),b=new Date(k+'T00:00:00'),d=Math.round((b-a)/86400000);state.stats.streak=d===1?state.stats.streak+1:1;state.stats.lastDay=k}
function renderAll(){
 updateStreak();$('#streak').textContent=state.stats.streak;$('#stars').textContent=state.stats.stars;$('#levelBadge').textContent=levelName();$('#placementBanner').hidden=state.placementDone;$('#dailyArea').hidden=!state.placementDone;
 ['f','v','g','i'].forEach(function(k){var cap=k.toUpperCase();$('#score'+cap).textContent=state.scores[k];$('#bar'+cap).style.width=state.scores[k]+'%'});
 $('#parentLevel').textContent=levelName();$('#placementDate').textContent=state.placementDate?('评估于 '+state.placementDate):'尚未评估';$('#parentAnswers').textContent=state.stats.answers;$('#parentMinutes').textContent=Math.round(state.stats.minutes);
 if(state.placementDone){renderDaily();renderParent();renderKetReadiness()}else{$('#parentDaily').textContent='0/3';$('#parentInsight').textContent='先完成首次水平评估，系统才能判断当前阶段并生成学习任务。'}
 fillSettings();detectDevice();
}
function dailyPlan(){
 var wk=weakKey(),lvl=state.child.level,interest=state.child.interest;
 var topics={food:['shop','restaurant','weekend'],animals:['zoo','weekend','school'],sports:['weekend','school','zoo'],stories:['school','weekend','shop'],space:['school','weekend','airport'],travel:['airport','restaurant','weekend']}[interest]||['school','weekend','shop'];
 var dayIndex=(new Date().getDay()+new Date().getDate())%topics.length,scene=topics[dayIndex];
 var weak={f:'连续说完整句',v:'增加主题词汇',g:'把句型说准确',i:'主动回应并提问'}[wk];
 if(lvl==='ket')return [
   {id:'warmup',title:'KET Part 1 热身',mins:3,desc:'3轮个人问答，回答至少给2个信息点。',type:'ket1',turns:3},
   {id:'main',title:'KET Part 2 主题讨论',mins:8,desc:'围绕活动偏好讨论，给理由并回应搭档。',type:'ket2',turns:6},
   {id:'focus',title:'今日专项：'+weak,mins:4,desc:'把当前最弱能力放进真实对话里再练4轮。',type:'focus',scene:scene,turns:4}
 ];
 return [
   {id:'warmup',title:'口语热身',mins:3,desc:lvl==='prea1'?'完成3轮简单问答，每次至少说1个完整句。':'完成3轮快速问答，把嘴巴“热起来”。',type:'scene',scene:scene,turns:3},
   {id:'main',title:'真人情景对话',mins:8,desc:'进入“'+scenes[scene].title+'”连续对话，完成6轮自然交流。',type:'scene',scene:scene,turns:6},
   {id:'focus',title:'今日专项：'+weak,mins:4,desc:'针对当前短板再练4轮，系统会适当提高追问强度。',type:'focus',scene:topics[(dayIndex+1)%topics.length],turns:4}
 ];
}
function renderDaily(){
 var plan=dailyPlan(),day=ensureDay(),done=day.done||[],n=done.length;$('#todayDateLabel').textContent=todayKey()+' · '+levels[state.child.level].name;$('#dailyTitle').textContent='今天的 15 分钟口语课';$('#dailySummary').textContent='系统根据首次评估和最近练习，把今天固定拆成“热身 → 主对话 → 专项提升”。当前重点：'+weakName()+'。';$('#coachAdvice').innerHTML='今天不要追求说得快，先把<b>'+weakName()+'</b>练稳。完成 3 项任务后，明天会根据今天表现自动调整。';$('#dailyDoneText').textContent=n+' / 3';$('#dailyProgress').style.width=(n/3*100)+'%';$('#parentDaily').textContent=n+'/3';
 var box=$('#dailyTasks');box.innerHTML='';plan.forEach(function(t,idx){var card=document.createElement('article');card.className='task-card'+(done.indexOf(t.id)>=0?' done':'');card.innerHTML='<div class="task-no">'+(idx+1)+'</div><div class="task-check">'+(done.indexOf(t.id)>=0?'✅':'')+'</div><h3>'+escapeHtml(t.title)+'</h3><div class="task-meta">约 '+t.mins+' 分钟 · 目标 '+t.turns+' 轮</div><p>'+escapeHtml(t.desc)+'</p><button class="btn '+(done.indexOf(t.id)>=0?'secondary':'primary')+' taskStart" data-task="'+t.id+'">'+(done.indexOf(t.id)>=0?'再练一次':'开始任务')+'</button>';box.appendChild(card)});$$('.taskStart').forEach(function(b){b.onclick=function(){startDailyTask(b.dataset.task)}})
}
function startDailyTask(id){var t=dailyPlan().filter(function(x){return x.id===id})[0];if(!t)return;activeTask=t;activeTaskStartTurns=0;var day=ensureDay();if(day.started.indexOf(id)<0)day.started.push(id);save();if(t.type==='ket1')startKet('part1',true);else if(t.type==='ket2')startKet('part2',true);else{currentConversationType=t.type;$('#sceneSelect').value=t.scene||'school';go('chat');startScene(true,t.type==='focus')}renderActiveTask()}
function completeActiveTask(){if(!activeTask)return;var day=ensureDay();if(day.done.indexOf(activeTask.id)<0){day.done.push(activeTask.id);state.stats.stars+=5;toast('✅ 今日任务“'+activeTask.title+'”完成！');save()}renderActiveTask()}
function renderActiveTask(){if(!activeTask){$('#activeTaskInfo').textContent='从“今日学习”进入任务后，这里会显示目标轮次。';return}var progress=Math.max(0,chatTurns-activeTaskStartTurns);$('#activeTaskInfo').innerHTML='<b>'+escapeHtml(activeTask.title)+'</b><br>目标 '+activeTask.turns+' 轮，当前 '+Math.min(progress,activeTask.turns)+' / '+activeTask.turns+'。'}
function systemPrompt(sc,focus){var extra=focus?'Today focus specifically on the learner weakest area: '+weakName()+'. Give prompts that train this while staying natural.':'';return 'You are Leo, a warm one-on-one English speaking tutor for a '+state.child.age+'-year-old child. Current level: '+levels[state.child.level].name+'. '+levels[state.child.level].prompt+' Scenario: '+sc.title+'. Goal: '+sc.goal+'. '+extra+' Rules: 1) Speak mainly in simple natural English suitable for the level. 2) Ask ONE question at a time. 3) Tutor reply under 45 English words. 4) Encourage first and correct at most ONE important issue. 5) Always continue with a natural follow-up question. 6) Never ask for real address, phone, school name, passwords or other sensitive information. 7) Return ONLY valid JSON: {"reply":"English tutor reply","praise":"short Chinese praise","improve":"one short Chinese improvement tip","natural":"more natural English version of the child answer"}.'}
function ketPrompt(mode){if(mode==='part1')return 'Run A2 Key speaking Part 1 practice: simple personal and factual questions about daily life, free time, school subjects without asking school name, likes/dislikes, past experiences and future plans. Ask one at a time and encourage 2-3 information points.';if(mode==='part2')return 'Run A2 Key speaking Part 2. Topic activities: cycling, cinema, swimming, picnic and museum. Also play a friendly candidate partner Alex. Train likes/dislikes, reasons, reactions and asking the partner questions.';return 'Run a compact A2 Key speaking mock. Start with Part 1 questions, then clearly move to Part 2 discussion about activities. Play both interlocutor and a friendly partner.'}
function startScene(withLive,focus){var sc=scenes[$('#sceneSelect').value];currentConversationType=focus?'focus':'scene';live=!!withLive;chatTurns=0;activeTaskStartTurns=0;chatHistory=[{role:'system',content:systemPrompt(sc,focus)},{role:'assistant',content:sc.open}];$('#chatLog').innerHTML='';addMsg('assistant',sc.open,'目标：'+sc.goal);renderQuick(sc.quick);go('chat');setLiveUI(live?'老师正在说…':'单次模式');speak(sc.open);state.stats.sessions++;save()}
function startKet(mode,withLive){if(!state.placementDone){toast('建议先完成首次水平评估');go('assess');return}currentConversationType='ket';live=withLive!==false;chatTurns=0;activeTaskStartTurns=0;var sc={title:'A2 Key Speaking '+mode,goal:'KET speaking exam-style practice'};var open=mode==='part1'?"Hello! Let's start Part 1. What do you like doing in your free time?":mode==='part2'?"Let's do Part 2. Think about cycling, cinema, swimming, picnic and museum. Which activity do you like best, and why?":"Hello! This is your A2 Key speaking mock. First, tell me something about what you usually do after school.";chatHistory=[{role:'system',content:systemPrompt(sc,false)+' '+ketPrompt(mode)},{role:'assistant',content:open}];$('#chatLog').innerHTML='';addMsg('assistant',open,'KET '+mode.toUpperCase());renderQuick(['I usually…','I think… because…','What do you think?']);go('chat');setLiveUI(live?'老师正在说…':'单次模式');speak(open);state.stats.sessions++;save()}
$$('.ketStart').forEach(function(b){b.onclick=function(){startKet(b.dataset.ket,true)}});$('#sceneSelect').onchange=function(){activeTask=null;startScene(false,false)};
function renderQuick(arr){var q=$('#quickPhrases');q.innerHTML='';arr.forEach(function(t){var b=document.createElement('button');b.className='chip';b.textContent=t;b.onclick=function(){$('#speechText').value=t};q.appendChild(b)})}
function addMsg(role,text,meta){var d=document.createElement('div');d.className='msg '+(role==='assistant'?'ai':'me');d.textContent=text;if(meta){var s=document.createElement('small');s.textContent=meta;d.appendChild(s)}$('#chatLog').appendChild(d);$('#chatLog').scrollTop=$('#chatLog').scrollHeight}
function setAvatar(mode){var a=$('#chatAvatar');a.classList.remove('speaking','listening');if(mode)a.classList.add(mode)}
function setLiveUI(text){$('#liveBadge').classList.toggle('active',live);$('#liveText').textContent=live?'连续模式':'单次模式';$('#teacherState').textContent=text||(live?'连续对话进行中':'等待语音')}
function startNativeSpeech(target){nativeSpeechTarget=target;if(!(window.AndroidBridge&&AndroidBridge.startSpeech)){toast('Android 语音桥接不可用');return}if(target==='chat'){$('#speechText').value='';$('#speechStatus').textContent='正在启动麦克风…';setAvatar('listening');setLiveUI('正在听孩子说英语…')}else{$('#assessmentText').value='';$('#assessmentSpeechStatus').textContent='正在启动麦克风…'}AndroidBridge.startSpeech(target)}
$('#liveStart').onclick=function(){if(!state.placementDone){toast('请先完成首次水平评估');go('assess');return}live=true;activeTask=null;if(!chatHistory.length)startScene(true,false);else{setLiveUI('正在听孩子说英语…');startNativeSpeech('chat')}};
$('#liveStop').onclick=function(){live=false;if(window.AndroidBridge&&AndroidBridge.stopSpeech)AndroidBridge.stopSpeech();setAvatar('');setLiveUI('连续对话已结束')};
$('#singleSpeak').onclick=function(){if(!state.placementDone){toast('请先完成首次水平评估');go('assess');return}live=false;if(!chatHistory.length){startScene(false,false);toast('老师先问一个问题，听完后再点“单次说一句”');return}setLiveUI('单次语音输入');startNativeSpeech('chat')};
$('#manualSend').onclick=function(){sendAnswer($('#speechText').value.trim())};
window.onNativeSpeechState=function(s){if(s==='ready'||s==='speaking'){if(nativeSpeechTarget==='assessment'){$('#assessmentSpeechStatus').textContent='正在听…'}else{$('#speechStatus').textContent='正在听…请自然说英语';setAvatar('listening');setLiveUI('正在听孩子说英语…')}}else if(s==='processing'){if(nativeSpeechTarget==='assessment')$('#assessmentSpeechStatus').textContent='识别中…';else{$('#speechStatus').textContent='识别中…';setLiveUI('正在识别…')}}};
window.onNativeSpeechPartial=function(target,text){nativeSpeechTarget=target;if(target==='assessment'){$('#assessmentText').value=text;$('#assessmentSpeechStatus').textContent='正在识别：'+text}else{$('#speechText').value=text;$('#speechStatus').textContent='正在识别：'+text}};
window.onNativeVoiceLevel=function(v){var h=Math.max(5,Math.min(22,5+Math.max(0,v)*1.3));$$('#voiceWave i').forEach(function(x,i){x.style.height=Math.max(4,h-(i%3)*3)+'px'})};
window.onNativeSpeech=function(target,text,conf){nativeSpeechTarget=target;lastConfidence=conf;if(target==='assessment'){$('#assessmentText').value=text;$('#assessmentSpeechStatus').textContent='识别完成，可以提交本题';return}$('#speechText').value=text;$('#speechStatus').textContent='识别完成，正在发送…';if(text.trim())setTimeout(function(){sendAnswer(text.trim())},80)};
window.onNativeSpeechError=function(msg){setAvatar('');if(nativeSpeechTarget==='assessment')$('#assessmentSpeechStatus').textContent=msg;else{$('#speechStatus').textContent=msg;setLiveUI(msg)}if(live&&(msg.indexOf('没有听清')>=0||msg.indexOf('没有检测')>=0)){setTimeout(function(){if(live)startNativeSpeech('chat')},800)}};
window.onNativeTtsStart=function(){setAvatar('speaking');setLiveUI('Leo 老师正在说…')};
window.onNativeTtsDone=function(){setAvatar('');if(live){setLiveUI('轮到你了，正在听…');setTimeout(function(){if(live)startNativeSpeech('chat')},420)}else setLiveUI('老师说完了，可以开始回答')};
window.onNativeTtsError=function(msg){$('#teacherState').textContent=msg};
function speak(t){if(window.AndroidBridge&&AndroidBridge.speak)AndroidBridge.speak(t)}
function localCoach(text){var m=analyzeText(text),p=m.words>=10?'回答比较完整，表达很清楚。':'意思已经说清楚了，愿意开口很好。',im=m.links?'继续注意自然停顿和语速。':'下一句试着加入 because / and，把答案再扩展一点。',r=m.words<6?'Good! Can you tell me one more thing?':m.links?'Great answer! What else can you tell me?':'Nice! Why? Try to use “because”.';return{reply:r,praise:p,improve:im,natural:capitalize(text)}}
function sendAnswer(text){text=(text||'').trim();if(!text)return;if(!chatHistory.length){toast('请先开始一个对话');return}addMsg('user',text,lastConfidence>=0?('识别置信度约 '+Math.round(lastConfidence*100)+'%'):'');$('#speechText').value='';chatTurns++;state.stats.answers++;state.stats.minutes+=.7;state.stats.stars+=2;$('#metricTurns').textContent=chatTurns;updateScores(text);renderActiveTask();chatHistory.push({role:'user',content:text});if(activeTask&&chatTurns-activeTaskStartTurns>=activeTask.turns)completeActiveTask();var btn=$('#manualSend');btn.disabled=true;btn.textContent='AI 老师思考中…';deepseek(chatHistory,function(ok,val){var out;if(ok){out=parseTutorJson(val)||localCoach(text);$('#aiMode').textContent='· Flash 在线'}else{out=localCoach(text);$('#aiMode').textContent='· 本地兜底';toast('DeepSeek 未连接，已用本地陪练继续')};chatHistory.push({role:'assistant',content:out.reply});addMsg('assistant',out.reply);$('#liveFeedback').innerHTML='<b>做得好：</b>'+escapeHtml(out.praise)+'<br><b>改进一点：</b>'+escapeHtml(out.improve)+'<br><b>更自然：</b>'+escapeHtml(out.natural||text);speak(out.reply);btn.disabled=false;btn.textContent='发送输入文字';state.history.push({date:new Date().toISOString(),level:state.child.level,text:text,score:clone(state.scores)});save()})}
function parseTutorJson(raw){try{var s=raw.indexOf('{'),e=raw.lastIndexOf('}');if(s<0||e<s)return null;var o=JSON.parse(raw.slice(s,e+1));return o.reply?o:null}catch(e){return null}}
function capitalize(t){return t?t.charAt(0).toUpperCase()+t.slice(1).replace(/[.?!]*$/,'.'):t}
function analyzeText(t){var w=t.trim().split(/\s+/).filter(Boolean),clean=w.map(function(x){return x.toLowerCase().replace(/[^a-z']/g,'')}).filter(Boolean),u=new Set(clean),links=(t.match(/\b(and|because|but|so|then|also|although|however)\b/ig)||[]).length,past=/\b(went|was|were|did|had|played|visited|watched|ate|saw|made|got|bought|came|took)\b/i.test(t),future=/\b(will|going to|would like|want to)\b/i.test(t),habit=/\b(usually|often|sometimes|always|never|every)\b/i.test(t),question=t.indexOf('?')>=0,complex=/\b(although|however|if|when|while|which|who|that)\b/i.test(t);return{words:w.length,unique:u.size,links:links,past:past,future:future,habit:habit,question:question,complex:complex}}
function metric(t){var m=analyzeText(t),f=clamp(38+Math.min(m.words,22)*2.2+m.links*4),v=clamp(42+Math.min(m.unique,18)*2.2),g=clamp(45+m.links*5+(m.past?8:0)+(m.future?6:0)+(m.habit?5:0)+(m.complex?8:0)),i=clamp(42+Math.min(m.words,14)*2+(m.question?12:0)+m.links*3);return{f:f,v:v,g:g,i:i,raw:m}}
function updateScores(text){var m=metric(text);['f','v','g','i'].forEach(function(k){state.scores[k]=clamp(state.scores[k]*.78+m[k]*.22)});$('#metricWords').textContent=m.raw.words+' 词';$('#metricLinks').textContent=m.raw.links?m.raw.links+' 个':'未使用';$('#metricConfidence').textContent=lastConfidence>=0?Math.round(lastConfidence*100)+'%':'—'}
function hasApi(){try{return !!(window.AndroidBridge&&AndroidBridge.hasApiKey&&AndroidBridge.hasApiKey())}catch(e){return false}}
function deepseek(messages,cb){if(!hasApi()){cb(false,'未保存 API Key');return}var id='r'+(++requestSeq)+'_'+Date.now();pending[id]=cb;try{AndroidBridge.chat(JSON.stringify(messages),id)}catch(e){delete pending[id];cb(false,e.message)}}
window.onAndroidChat=function(id,ok,val){var cb=pending[id];if(!cb)return;delete pending[id];cb(ok,val)};
function prepareAssessment(){assessmentMode=state.placementDone?'reassess':'placement';$('#assessType').textContent=assessmentMode==='placement'?'PLACEMENT':'REASSESSMENT';$('#assessTitle').textContent=assessmentMode==='placement'?'首次口语水平评估':'阶段复测';$('#assessmentResult').hidden=true;assessmentIndex=0;assessmentAnswers=[];renderAssessmentQuestion()}
function currentAssessmentQuestions(){return assessmentMode==='placement'?placementQuestions:reassessQuestions[state.child.level]}
function renderAssessmentQuestion(){var arr=currentAssessmentQuestions(),q=arr[assessmentIndex];$('#questionNo').textContent=assessmentIndex+1;$('#questionTotal').textContent=arr.length;$('#questionText').textContent=q.q;$('#questionHint').textContent=q.hint;$('#assessmentText').value='';$('#assessmentSpeechStatus').textContent='等待回答'}
$('#startPlacement').onclick=function(){go('assess')};$('#resetAssessment').onclick=function(){assessmentIndex=0;assessmentAnswers=[];$('#assessmentResult').hidden=true;renderAssessmentQuestion()};$('#assessmentMic').onclick=function(){startNativeSpeech('assessment')};$('#sampleAssessment').onclick=function(){$('#assessmentText').value=currentAssessmentQuestions()[assessmentIndex].sample};
$('#submitAssessment').onclick=function(){var t=$('#assessmentText').value.trim();if(!t){toast('请先回答本题');return}assessmentAnswers.push({q:currentAssessmentQuestions()[assessmentIndex].q,text:t,m:metric(t)});assessmentIndex++;if(assessmentIndex<currentAssessmentQuestions().length){renderAssessmentQuestion();toast('已记录，进入下一题')}else finishAssessment()};
function placementScore(){var total=0;assessmentAnswers.forEach(function(a){var m=a.m.raw,base=m.words<=4?34:m.words<=8?49:m.words<=14?61:m.words<=20?71:78;base+=Math.min(m.links,3)*5+(m.past?5:0)+(m.future?4:0)+(m.habit?3:0)+(m.question?6:0)+(m.complex?7:0);total+=clamp(base)});return Math.round(total/assessmentAnswers.length)}
function levelFromPlacement(s){if(s<45)return'prea1';if(s<61)return'a1';if(s<78)return'ket';return'b1'}
function finishAssessment(){['f','v','g','i'].forEach(function(k){state.scores[k]=clamp(assessmentAnswers.reduce(function(a,x){return a+x.m[k]},0)/assessmentAnswers.length)});var avg=Math.round((state.scores.f+state.scores.v+state.scores.g+state.scores.i)/4),pScore=assessmentMode==='placement'?placementScore():avg;if(assessmentMode==='placement'){state.child.level=levelFromPlacement(pScore);state.placementDone=true;state.placementDate=todayKey();state.manualLevel=false;state.daily={}}state.stats.answers+=assessmentAnswers.length;state.stats.minutes+=assessmentAnswers.length*.7;state.stats.stars+=10;save();var text='系统判断当前阶段为 <b>'+levels[state.child.level].name+'</b>。四维平均分为 <b>'+avg+'</b>，当前最需要优先提升的是 <b>'+weakName()+'</b>。接下来每天会固定生成“3分钟热身 + 8分钟主对话 + 4分钟专项提升”，并根据每次练习动态调整难度。';if(state.child.level==='ket')text+=' 已进入 A2 Key/KET 口语训练区间，日常任务会加入 Part 1 和 Part 2。';$('#overallScore').textContent=pScore;$('#placementResultText').innerHTML=text;$('#assessmentResult').hidden=false;renderWeeklyPlan();requestAssessmentSummary();toast('评估完成，已生成定制学习内容')}
function requestAssessmentSummary(){if(!hasApi())return;var payload={level:levels[state.child.level].name,scores:state.scores,answers:assessmentAnswers.map(function(x){return x.text})};deepseek([{role:'system',content:'You are a careful children English speaking assessor. Write a concise Chinese parent summary. Do not claim professional pronunciation scoring.'},{role:'user',content:'Summarize strengths, the top weakness and practical next steps from: '+JSON.stringify(payload)}],function(ok,val){if(ok){state.aiSummary=val;save()}})}
$('#goDailyAfterAssessment').onclick=function(){go('home')};$('#goPlanAfterAssessment').onclick=function(){go('plan')};
function renderWeeklyPlan(){var box=$('#weeklyPlan');box.innerHTML='';if(!state.placementDone){$('#planSummary').innerHTML='<b>尚未完成首次评估</b><p>先完成水平评估后再生成 7 天计划。</p>';return}var wk=weakName(),ket=state.child.level==='ket';$('#planSummary').innerHTML='<b>'+levels[state.child.level].name+' · 本周重点：'+wk+'</b><p class="feedback">每天固定 15 分钟。任务结构保持不变，但主题和追问会根据表现变化。</p>';var ds=ket?[["Part 1 热身",'完整回答','每题给2–3个信息点'],['日常生活问答','频率与习惯','练 usually / often / after school'],['Part 2 偏好讨论','给理由','多用 because / I think'],['搭档互动','主动提问','至少主动问4次'],['过去经历','时态表达','练 last weekend / yesterday'],['完整模拟','连贯与互动','完成 Part 1 + Part 2'],['周测复盘','更新计划','阶段复测并复练薄弱题']]:[['生活情景','建立口语节奏','完成连续情景对话'],['跟读与改说','流利度','听一句后换关键词重说'],['兴趣话题','连续表达','回答后再补一句细节'],['错句回访','准确度','把常见错句重新说对'],['连接词','扩展句子','练 and / because / but'],['自由聊天','互动能力','主动问老师3个问题'],['周测复盘','动态调整','复测并更新下周难度']];ds.forEach(function(d,i){var c=document.createElement('article');c.className='week-day';c.innerHTML='<small>DAY '+(i+1)+'</small><h3>'+d[0]+'</h3><b>'+d[1]+'</b><p>'+d[2]+'</p><span class="sub">15 min</span>';box.appendChild(c)})}
$('#refreshPlan').onclick=function(){renderWeeklyPlan();toast('已按最新学习数据更新')};
function renderParent(){var day=ensureDay(),done=(day.done||[]).length;$('#parentDaily').textContent=done+'/3';var strong=Object.keys(state.scores).sort(function(a,b){return state.scores[b]-state.scores[a]})[0],map={f:'流利度',v:'词汇表达',g:'语法准确',i:'互动能力'};var base='<b>当前优势：</b>'+map[strong]+'相对较好。<br><b>重点提升：</b>'+weakName()+'。<br><b>建议：</b>每天完成 3 项固定任务即可，坚持比单次练很久更重要。';if(state.aiSummary)base+='<br><br><b>AI 最近评估：</b>'+escapeHtml(state.aiSummary).replace(/\n/g,'<br>');$('#parentInsight').innerHTML=base}
function renderKetReadiness(){var order={prea1:0,a1:1,ket:2,b1:3},ready=order[state.child.level]>=2;$('#ketReadiness').innerHTML=ready?'当前评估为 <b>'+levels[state.child.level].name+'</b>，可以把 KET Part 1 / Part 2 作为主要训练内容。':'当前评估为 <b>'+levels[state.child.level].name+'</b>。可以提前体验 KET，但每日任务仍优先补基础能力。'}
function fillSettings(){$('#childName').value=state.child.name;$('#childAge').value=String(state.child.age);$('#childInterest').value=state.child.interest;$('#manualLevel').value=state.child.level;renderKeyStatus()}
function renderKeyStatus(){var yes=hasApi(),x=$('#keyStatus');x.className='notice '+(yes?'ok':'');x.innerHTML=yes?'✅ 本机已保存 API Key，模型固定为 <b>DeepSeek V4 Flash</b>。':'尚未保存 API Key。保存后可使用连续 AI 对话和智能总结。'}
$('#toggleKey').onclick=function(){var x=$('#apiKey');x.type=x.type==='password'?'text':'password';this.textContent=x.type==='password'?'显示':'隐藏'};
$('#saveAndTestKey').onclick=function(){var k=$('#apiKey').value.trim(),box=$('#keyStatus');if(!(window.AndroidBridge&&AndroidBridge.saveApiKey)){box.className='notice bad';box.textContent='Android API 桥接不可用';return}var r=AndroidBridge.saveApiKey(k);if(r!=='OK'){box.className='notice bad';box.textContent='❌ '+r;return}box.className='notice';box.textContent='正在测试 DeepSeek V4 Flash…';deepseek([{role:'user',content:'Reply with exactly OK'}],function(ok,val){box.className='notice '+(ok?'ok':'bad');box.textContent=ok?'✅ 连接成功，Flash 可用。':'❌ 连接失败：'+val;toast(ok?'DeepSeek 连接成功':'DeepSeek 连接失败')})};
$('#clearKey').onclick=function(){if(window.AndroidBridge&&AndroidBridge.clearApiKey)AndroidBridge.clearApiKey();$('#apiKey').value='';renderKeyStatus();toast('API Key 已清除')};
$('#saveProfile').onclick=function(){state.child.name=$('#childName').value.trim()||'Mia';state.child.age=Number($('#childAge').value)||9;state.child.interest=$('#childInterest').value;var lv=$('#manualLevel').value;if(state.placementDone&&lv!==state.child.level){state.child.level=lv;state.manualLevel=true;state.daily={}}save();toast('孩子档案已保存')};
function detectDevice(){try{$('#speechSupport').textContent=(window.AndroidBridge&&AndroidBridge.speechAvailable&&AndroidBridge.speechAvailable())?'可用':'不可用';$('#ttsSupport').textContent=(window.AndroidBridge&&AndroidBridge.ttsAvailable&&AndroidBridge.ttsAvailable())?'可用':'初始化中/不可用'}catch(e){$('#speechSupport').textContent='不可用';$('#ttsSupport').textContent='不可用'}}
$('#testVoice').onclick=function(){speak("Hello! I'm Leo. Let's practice English together!")};
function escapeHtml(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){return{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[c]})}
renderAll();renderWeeklyPlan();
})();