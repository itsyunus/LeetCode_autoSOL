"use strict";
const API = "/api/github";
const DEFAULT_REPO = "itsyunus/LeetCode_autoSOL";
const WORKFLOW = "daily_solve.yml";
const $ = (id) => document.getElementById(id);
let repo = localStorage.getItem("lc-control-repo") || DEFAULT_REPO;
let unlocked = false;
let latestRuns = [];
let refreshTimer = null;

$("repo").value = repo;


function headers(){return {"Accept":"application/vnd.github+json","X-GitHub-Api-Version":"2022-11-28"};}
async function api(path, options={}){
  const response = await fetch(API + "?path=" + encodeURIComponent(path), { ...options, credentials:"same-origin", headers:{...headers(),...(options.headers||{})} });
  if(response.status===204)return null;
  const text=await response.text();
  let data={};try{data=text?JSON.parse(text):{};}catch(_){throw new Error("GitHub returned an unexpected response (HTTP "+response.status+").");}
  if(!response.ok){
    if(response.status===401)throw new Error("Your dashboard session expired. Unlock it again.");
    if(response.status===403)throw new Error("GitHub denied this request. Check the server token permissions and repository access.");
    if(response.status===404)throw new Error("Repository or workflow was not found. Check the owner/repository name.");
    throw new Error(data.message||("GitHub API request failed (HTTP "+response.status+")."));
  }
  return data;
}
function escapeHtml(value){return String(value??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));}
function dateLabel(value){if(!value)return "Time unavailable";const d=new Date(value);return Number.isNaN(d.getTime())?"Time unavailable":d.toLocaleString(undefined,{month:"short",day:"numeric",hour:"numeric",minute:"2-digit"});}
function stateLabel(run){if(run.status!=="completed")return run.status==="in_progress"?"In progress":"Queued";return run.conclusion==="success"?"Completed":(run.conclusion||"Completed").replaceAll("_"," ");}
function stateClass(run){if(run.status!=="completed")return "active";if(run.conclusion==="success")return "success";if(run.conclusion==="failure"||run.conclusion==="cancelled"||run.conclusion==="timed_out")return "failure";return "";}
function notice(message,type=""){const n=$("notice");n.textContent=message;n.className="notice"+(type?" "+type:"");}
function clearNotice(){$("notice").className="notice hidden";$("notice").textContent="";}
function setConnected(connected){$("connection-pill").className="pill "+(connected?"good":"neutral");$("connection-pill").innerHTML="<i></i>"+(connected?"GitHub connected":"Not connected");$("run-btn").disabled=!connected;}
function setHealth(title,desc,state=""){ $("health-title").textContent=title;$("health-desc").textContent=desc;$("health-dot").className="health-dot "+state;}
function validateRepo(value){const v=value.trim();if(!/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(v))throw new Error("Repository must use owner/repository format.");return v;}
function baseRepo(){return "/repos/"+encodeURIComponent(repo.split("/")[0])+"/"+encodeURIComponent(repo.split("/")[1]);}
async function connect(){
  try{
    repo=validateRepo($("repo").value);
    if(!unlocked)throw new Error("Unlock the dashboard first.");
    $("connect-btn").disabled=true;$("connect-btn").textContent="Connecting…";
    const [repository,workflow]=await Promise.all([api(baseRepo()),api(baseRepo()+"/actions/workflows/"+WORKFLOW)]);
    if(repository.full_name.toLowerCase()!==repo.toLowerCase())throw new Error("GitHub returned a different repository than expected.");
    if(workflow.state!=="active")throw new Error("The daily solver workflow is not active in this repository.");
    localStorage.setItem("lc-control-repo",repo);
    $("repo").value=repo;
    setConnected(true);clearNotice();setHealth("Connected to GitHub","Workflow found: "+workflow.name,"good");
    await refreshAll();
    if(!refreshTimer)refreshTimer=setInterval(()=>{if(document.visibilityState==="visible"&&unlocked)refreshAll(true).catch(()=>{});},30000);
  }catch(error){setConnected(false);notice(error.message,"error");setHealth("Connection needs attention",error.message,"bad");}
  finally{$("connect-btn").disabled=false;$("connect-btn").textContent="Check GitHub connection";}
}
function renderResult(result){
  if(!result){$("stat-result").textContent="—";$("stat-result-sub").textContent="No saved result found";return;}
  const status=String(result.status||"unknown").replaceAll("_"," ");
  $("stat-result").textContent=status.charAt(0).toUpperCase()+status.slice(1);
  $("stat-result-sub").textContent=result.date?"Updated "+dateLabel(result.date):"Latest saved result";
  const p=result.problem||{};
  $("stat-problem").textContent=p.id?"#"+p.id+" "+(p.title||"Problem"): "—";
  $("stat-problem-sub").textContent=[p.difficulty,p.date].filter(Boolean).join(" · ")||"Problem details";
  const sub=result.submission||{};
  $("stat-runtime").textContent=sub.runtime||"—";
  $("stat-runtime-sub").textContent=sub.memory?"Memory "+sub.memory:(sub.language||"Execution time");
  $("auth-status").textContent=result.status==="accepted"||result.status==="already_solved"?"Last run authenticated":"See latest run";
}
async function loadLatestResult(){
  try{
    const listing=await api(baseRepo()+"/contents/logs?ref=main");
    const files=listing.filter(item=>item.type==="file"&&/^result_\d{4}-\d{2}-\d{2}\.json$/.test(item.name)).sort((a,b)=>b.name.localeCompare(a.name));
    if(!files.length){renderResult(null);return;}
    const file=await api(baseRepo()+"/contents/"+files[0].path.split("/").map(encodeURIComponent).join("/")+"?ref=main");
    const decoded=decodeURIComponent(escape(atob((file.content||"").replace(/\n/g,""))));
    renderResult(JSON.parse(decoded));
  }catch(error){$("stat-result-sub").textContent="Result file unavailable";$("auth-status").textContent="Not verified";}
}
function renderRuns(runs){
  latestRuns=runs||[];const list=$("runs-list");
  if(!latestRuns.length){list.innerHTML='<div class="empty-state">No workflow runs found yet.</div>';return;}
  list.innerHTML=latestRuns.slice(0,8).map(run=>{
    const title=run.display_title||run.name||"LeetCode solver";
    const mode=run.event==="schedule"?"Scheduled":(run.inputs&&run.inputs.dry_run==="true"?"Dry run":run.event==="workflow_dispatch"?"Manual":"Workflow");
    return '<div class="run-item"><div class="run-main"><div class="run-name">'+escapeHtml(title)+'</div><div class="run-meta">#'+run.run_number+' · '+escapeHtml(mode)+' · '+escapeHtml(dateLabel(run.created_at))+'</div></div><span class="run-badge '+stateClass(run)+'">'+escapeHtml(stateLabel(run))+'</span><button class="run-open" data-run="'+run.id+'">Details ↗</button></div>';
  }).join("");
  list.querySelectorAll("[data-run]").forEach(button=>button.addEventListener("click",()=>loadRunDetails(button.dataset.run)));
}
async function refreshAll(silent=false){
  if(!unlocked)return;
  try{
    const data=await api(baseRepo()+"/actions/workflows/"+WORKFLOW+"/runs?per_page=10");
    renderRuns(data.workflow_runs||[]);
    await loadLatestResult();
    const active=latestRuns.find(run=>run.status!=="completed");
    if(active){setHealth("Solver is running",stateLabel(active)+" · run #"+active.run_number,"good");$("run-btn").disabled=true;}
    else{setHealth("Automation is ready","Latest workflow status: "+(latestRuns[0]?stateLabel(latestRuns[0]):"No runs yet"),"good");$("run-btn").disabled=false;}
    if(!silent)clearNotice();
  }catch(error){if(!silent)notice(error.message,"error");if(/session expired|permission|access|server token/i.test(error.message)){setConnected(false);setHealth("Connection needs attention",error.message,"bad");}}
}
async function runNow(){
  if(!unlocked)return;
  const active=latestRuns.find(run=>run.status!=="completed");
  if(active){notice("A workflow is already running. Wait for it to finish before starting another.","");return;}
  const dry=$("dry-run").checked;
  const prompt=dry?"Start a dry run? This will generate and validate without submitting.":"Start a LIVE run? This may submit a solution to your LeetCode account.";
  if(!window.confirm(prompt))return;
  $("run-btn").disabled=true;$("run-btn").textContent="Queuing…";notice("Sending workflow dispatch to GitHub…");
  const started=Date.now();
  try{
    await api(baseRepo()+"/actions/workflows/"+WORKFLOW+"/dispatches",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({ref:"main",inputs:{dry_run:dry?"true":"false",language:$("language").value}})});
    notice(dry?"Dry run queued. Waiting for GitHub to publish its run…":"Live run queued. Waiting for GitHub to publish its run…","success");
    for(let i=0;i<10;i++){
      await new Promise(resolve=>setTimeout(resolve,1800));
      const data=await api(baseRepo()+"/actions/workflows/"+WORKFLOW+"/runs?event=workflow_dispatch&branch=main&per_page=8");
      const run=(data.workflow_runs||[]).find(item=>Date.parse(item.created_at)>=started-8000);
      if(run){await refreshAll(true);await loadRunDetails(run.id);notice("Workflow queued successfully. You can monitor its progress here.","success");break;}
    }
    if($("notice").textContent.includes("Waiting"))notice("GitHub accepted the dispatch. The run may take a few seconds to appear; refresh the dashboard shortly.","success");
  }catch(error){notice(error.message,"error");}
  finally{$("run-btn").disabled=!unlocked;$("run-btn").innerHTML='<span>▶</span> Run now <span class="btn-arrow">→</span>';}
}
async function loadRunDetails(id){
  try{
    const run=latestRuns.find(item=>String(item.id)===String(id));
    const [jobsData,artifactsData]=await Promise.all([api(baseRepo()+"/actions/runs/"+id+"/jobs"),api(baseRepo()+"/actions/runs/"+id+"/artifacts")]);
    $("detail-title").textContent="Run #"+(run?run.run_number:id);
    $("detail-link").href=run?run.html_url:"https://github.com/"+repo+"/actions/runs/"+id;
    const jobs=(jobsData.jobs||[]).map(job=>'<div class="job-row"><span>'+escapeHtml(job.name)+'</span><small>'+escapeHtml(job.status==="completed"?(job.conclusion||"completed"):job.status)+'</small></div>').join("");
    const artifacts=(artifactsData.artifacts||[]).map(item=>'<a class="artifact-link" href="'+escapeHtml("https://github.com/"+repo+"/actions/runs/"+id)+'/artifacts" target="_blank" rel="noopener">'+escapeHtml(item.name)+' · '+Math.round(item.size_in_bytes/1024)+' KB ↗</a>').join("");
    $("detail-content").innerHTML='<div class="job-list">'+(jobs||'<div class="empty-state">Job details are not available yet.</div>')+'</div>'+(artifacts?'<div class="small-note">Artifacts</div>'+artifacts:'');
    $("run-detail").classList.remove("hidden");$("run-detail").scrollIntoView({behavior:"smooth",block:"start"});
  }catch(error){notice("Could not load run details: "+error.message,"error");}
}
$("connect-btn").addEventListener("click",connect);
$("run-btn").addEventListener("click",runNow);
$("refresh-btn").addEventListener("click",()=>refreshAll());
$("forget-btn").addEventListener("click",()=>{
  fetch("/api/logout",{method:"POST",credentials:"same-origin"}).catch(()=>{});
  unlocked=false;if(refreshTimer){clearInterval(refreshTimer);refreshTimer=null;}
  setConnected(false);setHealth("Dashboard locked","Enter your passcode to activate automation.");
  $("lock-screen").classList.remove("hidden");$("passcode").value="";notice("Dashboard locked.","success");
});
$("dry-run").addEventListener("change",()=>{$("dry-hint").textContent=$("dry-run").checked?"Dry run generates and validates a solution without submitting it to LeetCode.":"Live mode may submit a solution to your LeetCode account.";});
document.querySelectorAll(".mobile-nav a").forEach(link=>link.addEventListener("click",()=>{document.querySelectorAll(".mobile-nav a").forEach(item=>item.classList.remove("selected"));link.classList.add("selected");}));
if("serviceWorker" in navigator)window.addEventListener("load",()=>navigator.serviceWorker.register("./sw.js").catch(()=>{}));
async function checkSession(){
  try{
    const response=await fetch("/api/session",{credentials:"same-origin",cache:"no-store"});
    const data=await response.json();
    unlocked=Boolean(response.ok&&data.authenticated);
    if(unlocked){$("lock-screen").classList.add("hidden");await connect();}
    else{$("lock-screen").classList.remove("hidden");setConnected(false);}
  }catch(_){$("lock-screen").classList.remove("hidden");setConnected(false);}
}
$("unlock-form").addEventListener("submit",async event=>{
  event.preventDefault();
  const button=$("unlock-btn"),error=$("unlock-error");
  button.disabled=true;button.textContent="Unlocking…";error.textContent="";
  try{
    const response=await fetch("/api/unlock",{method:"POST",headers:{"Content-Type":"application/json"},credentials:"same-origin",body:JSON.stringify({passcode:$("passcode").value})});
    const data=await response.json();
    if(!response.ok)throw new Error(data.error||"Unable to unlock dashboard.");
    unlocked=true;$("lock-screen").classList.add("hidden");$("passcode").value="";
    await connect();
  }catch(err){error.textContent=err.message;$("passcode").select();}
  finally{button.disabled=false;button.innerHTML='Unlock dashboard <span class="btn-arrow">→</span>';}
});
checkSession();
