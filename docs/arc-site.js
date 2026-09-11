(() => {
  const root = document.documentElement;
  const reduceMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const installSnippets = {
    source: `git clone https://github.com/anatwork14/adaptive-agent-runtime.git\ncd adaptive-agent-runtime\npython -m venv .venv\nsource .venv/bin/activate\npip install -e ".[dev]"\narc --help`,
    init: `# run inside a clean git repository\narc init . --project-id demo\narc status --project-id demo\narc events --project-id demo`,
    docker: `# optional: build ARC's command/test sandbox image\ndocker build -f Dockerfile.runner -t arc-runner:latest .\n\n# provider CLI execution remains experimental host-mode\n# until provider auth/credential brokering is containerized.`
  };

  const demo = [
    {
      title: '01 // Initialize ARC', mode: 'REAL COMMAND', progress: '20%', phase: '#64ddff', phase2: '#a98cff', language: 'shell',
      code: `arc init . --project-id demo\narc status --project-id demo`,
      output: `$ arc init . --project-id demo\nInitialized ARC runtime in .arc (Project: demo)\n\n$ arc status --project-id demo\nProject: demo (State Version: 1)\nStatus: active`,
      events: [
        ['info','project.created','authoritative event appended'],
        ['ready','state.version = 1','projection synchronized'],
        ['accept','runtime ready','operator can create tasks']
      ]
    },
    {
      title: '02 // Run a zero-credential smoke task', mode: 'REAL PYTHON API', progress: '40%', phase: '#a98cff', phase2: '#ff6db0', language: 'python',
      code: `python - <<'PY'\nimport asyncio, sqlite3\nfrom pathlib import Path\nfrom adapters.mock import MockAgentAdapter\nfrom memory.lifecycle import MemoryLifecycle\nfrom runtime.orchestrator import Orchestrator\nfrom state.events import EventStore\n\nasync def main():\n    repo = Path('.').resolve()\n    db = repo / '.arc' / 'state.db'\n    store = EventStore(db)\n    conn = sqlite3.connect(db)\n    conn.row_factory = sqlite3.Row\n    memory = MemoryLifecycle(conn)\n    arc = Orchestrator(store, memory, repo, 'demo')\n    arc.create_task(\n        task_id='hello-arc',\n        goal='Create a traceable ARC demo artifact',\n        files_declared=['arc_demo.txt'],\n        acceptance_criteria=['artifact integrates through the gate'],\n        risk=0.2,\n    )\n    result = await arc.execute_task(\n        'hello-arc', MockAgentAdapter('demo-agent'), 'demo-agent'\n    )\n    print(result.status, result.merged_commit_sha)\n    conn.close(); store.close()\n\nasyncio.run(main())\nPY`,
      output: `[context] compiled immutable ContextPacket\n[worktree] created isolated task branch\n[agent] wrote arc_demo.txt\n[candidate] committed immutable candidate SHA\n[gate] candidate applied to fresh verification tree\n[gate] static verification passed\n[integration] candidate cherry-picked into integration branch\nACCEPTED <merged-commit-sha>`,
      events: [
        ['memory','context.compiled','bounded packet + code evidence'],
        ['info','worktree.created','isolated task branch'],
        ['commit','candidate.commit','immutable candidate SHA'],
        ['warn','gate.started','verifying exact candidate tree'],
        ['accept','gate.accepted','candidate passed verification'],
        ['ready','integration.complete','commit landed serially']
      ]
    },
    {
      title: '03 // Inspect authoritative state', mode: 'REAL COMMANDS', progress: '60%', phase: '#ff6db0', phase2: '#f4a340', language: 'shell',
      code: `arc status --project-id demo\narc events --project-id demo\narc replay --project-id demo`,
      output: `Task DAG\nhello-arc    completed\n\nAuthoritative events\nproject.created\ntask.created\ntask.dispatched\ncontext.compiled\ntask.submitted\ngate.started\ngate.accepted\n...\n\nReplay successful — project projection reconstructed from event history.`,
      events: [
        ['info','task.completed','DAG updated'],
        ['memory','events.read','append-only log inspected'],
        ['ready','replay.success','projection rebuilt from source of truth']
      ]
    },
    {
      title: '04 // Compile task context', mode: 'REAL COMMAND', progress: '80%', phase: '#c5f467', phase2: '#64ddff', language: 'shell',
      code: `arc context build hello-arc --agent demo --project-id demo`,
      output: `Compiled Context Packet: CTX_...\nDigest: sha256:...\nTokens: <used> / 24000\nDecisions Included: ...\nProcedures Included: ...\nFailures Included: ...\nMemory IDs: [...]`,
      events: [
        ['memory','memory.retrieve','active + valid memories only'],
        ['info','code.evidence','repository snippets hashed'],
        ['ready','context.digest','immutable packet sealed']
      ]
    },
    {
      title: '05 // Switch from mock to Codex', mode: 'REAL ADAPTER API', progress: '100%', phase: '#f4a340', phase2: '#c5f467', language: 'python',
      code: `# install + authenticate the Codex CLI first\n# ARC default adapter invocation: codex exec --full-auto -\n\nfrom adapters.codex import CodexAgentAdapter\n\nresult = await arc.execute_task(\n    'your-task-id',\n    CodexAgentAdapter(),\n    agent_id='codex',\n)\n\n# optional command override\n# export ARC_CODEX_COMMAND='codex exec --full-auto -'`,
      output: `ARC does not fabricate provider success.\nIf Codex is missing or exits unsuccessfully, the adapter fails explicitly.\nWhen it succeeds, ARC still requires a real repository change, candidate commit, and integration-gate acceptance.`,
      events: [
        ['warn','provider.boundary','real CLI required'],
        ['info','agent.codex','workspace-editing process launched'],
        ['commit','candidate.required','no fake successful diff'],
        ['ready','same gate','provider does not bypass ARC invariants']
      ]
    }
  ];

  const escapeHtml = value => String(value)
    .replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;');

  function highlightLine(line, language) {
    let s = escapeHtml(line);
    if (/^\s*#/.test(line)) return `<span class="tok-comment">${s}</span>`;
    if (language === 'shell') {
      s = s.replace(/(--[a-z0-9-]+)/gi,'<span class="tok-flag">$1</span>');
      s = s.replace(/\b(arc|git|python|pip|docker|source|cd|export)\b/g,'<span class="tok-shell">$1</span>');
      s = s.replace(/\b(init|status|events|replay|context|build|clone)\b/g,'<span class="tok-fn">$1</span>');
      s = s.replace(/\b(\d+(?:\.\d+)?)\b/g,'<span class="tok-num">$1</span>');
      return s;
    }
    const comments = [];
    s = s.replace(/(&#39;[^&#]*?&#39;|&quot;[^&]*?&quot;)/g, m => { const id = comments.push(`<span class="tok-string">${m}</span>`) - 1; return `@@S${id}@@`; });
    s = s.replace(/\b(async|await|def|from|import|as|return|for|in|if|else|with|class|True|False|None)\b/g,'<span class="tok-key">$1</span>');
    s = s.replace(/\b(Orchestrator|EventStore|MemoryLifecycle|MockAgentAdapter|CodexAgentAdapter|Path|Row)\b/g,'<span class="tok-class">$1</span>');
    s = s.replace(/\b(main|create_task|execute_task|connect|close|run|print|resolve)\b(?=\s*\()/g,'<span class="tok-fn">$1</span>');
    s = s.replace(/\b(arc|context|candidate|gate|memory|store|result)\b/g,'<span class="tok-arc">$1</span>');
    s = s.replace(/\b(\d+(?:\.\d+)?)\b/g,'<span class="tok-num">$1</span>');
    s = s.replace(/@@S(\d+)@@/g,(_,i)=>comments[Number(i)]);
    return s;
  }

  const installCode = document.getElementById('installCode');
  if (installCode) installCode.textContent = installSnippets.source;
  document.querySelectorAll('[data-install]').forEach(btn => btn.addEventListener('click', () => {
    document.querySelectorAll('[data-install]').forEach(x => x.setAttribute('aria-selected','false'));
    btn.setAttribute('aria-selected','true');
    installCode.textContent = installSnippets[btn.dataset.install];
  }));
  document.querySelectorAll('[data-copy-target]').forEach(btn => btn.addEventListener('click', async () => {
    const node = document.getElementById(btn.dataset.copyTarget); if (!node) return;
    try { await navigator.clipboard.writeText(node.textContent); const old=btn.textContent; btn.textContent='Copied'; setTimeout(()=>btn.textContent=old,1100); } catch { btn.textContent='Select + copy'; }
  }));

  const steps = [...document.querySelectorAll('[data-step]')];
  const title = document.getElementById('demoTitle');
  const mode = document.getElementById('demoMode');
  const lines = document.getElementById('demoLines');
  const events = document.getElementById('eventStream');
  const output = document.getElementById('demoOutput');
  const meter = document.getElementById('phaseProgress');
  const chamber = document.getElementById('executionChamber');
  const copyDemo = document.getElementById('copyDemo');
  const playDemo = document.getElementById('playDemo');
  let current = 0;
  let timer = null;
  let outputTimer = null;

  function renderEvents(items) {
    events.innerHTML = '';
    items.forEach((item,index) => {
      const [kind,name,detail] = item;
      const node = document.createElement('div');
      node.className = `event ${kind}`;
      node.style.animationDelay = reduceMotion ? '0ms' : `${index*95}ms`;
      node.innerHTML = `<strong>${escapeHtml(name)}</strong><small>${escapeHtml(detail)}</small>`;
      events.appendChild(node);
    });
  }

  function renderCode(step) {
    lines.innerHTML = '';
    const codeLines = step.code.split('\n');
    codeLines.forEach((line,index) => {
      const node = document.createElement('span');
      node.className = `code-line${index===Math.min(2,codeLines.length-1)?' active-line':''}`;
      node.style.animationDelay = reduceMotion ? '0ms' : `${Math.min(index,24)*28}ms`;
      node.innerHTML = highlightLine(line, step.language);
      if (index === codeLines.length - 1) node.insertAdjacentHTML('beforeend','<span class="caret" aria-hidden="true"></span>');
      lines.appendChild(node);
    });
  }

  function typeOutput(text) {
    if (outputTimer) { clearInterval(outputTimer); outputTimer = null; }
    if (reduceMotion) { output.textContent = text; return; }
    output.textContent = '';
    let i = 0;
    const chunk = Math.max(1, Math.ceil(text.length / 90));
    outputTimer = setInterval(() => {
      output.textContent += text.slice(i, i + chunk);
      i += chunk;
      if (i >= text.length) { clearInterval(outputTimer); outputTimer = null; }
    }, 14);
  }

  function render(index) {
    current = index;
    const step = demo[index];
    root.style.setProperty('--phase', step.phase);
    root.style.setProperty('--phase2', step.phase2);
    chamber.dataset.phase = String(index + 1);
    title.textContent = step.title;
    mode.textContent = step.mode;
    meter.style.setProperty('--progress', step.progress);
    steps.forEach((node,i)=>node.classList.toggle('active',i===index));
    renderCode(step);
    renderEvents(step.events);
    typeOutput(step.output);
  }

  steps.forEach(step => step.addEventListener('click', () => {
    if (timer) { clearInterval(timer); timer=null; playDemo.classList.remove('playing'); playDemo.textContent='Play walkthrough'; }
    render(Number(step.dataset.step));
  }));

  copyDemo?.addEventListener('click', async () => {
    try { await navigator.clipboard.writeText(demo[current].code); copyDemo.textContent='Copied'; setTimeout(()=>copyDemo.textContent='Copy current step',1100); } catch { copyDemo.textContent='Select + copy'; }
  });

  playDemo?.addEventListener('click', () => {
    if (timer) {
      clearInterval(timer); timer=null; playDemo.classList.remove('playing'); playDemo.textContent='Play walkthrough'; return;
    }
    playDemo.classList.add('playing'); playDemo.textContent='Pause walkthrough';
    timer=setInterval(()=>render((current+1)%demo.length),3300);
  });

  render(0);

  document.addEventListener('pointermove', e => {
    root.style.setProperty('--mx',`${e.clientX}px`);
    root.style.setProperty('--my',`${e.clientY}px`);
  });

  if (matchMedia('(hover:hover) and (pointer:fine)').matches && !reduceMotion) {
    document.querySelectorAll('.card').forEach(card => {
      card.addEventListener('pointermove', e => {
        const r=card.getBoundingClientRect(), x=(e.clientX-r.left)/r.width-.5, y=(e.clientY-r.top)/r.height-.5;
        card.style.transform=`perspective(760px) rotateX(${(-y*6).toFixed(2)}deg) rotateY(${(x*7).toFixed(2)}deg) translateY(-3px)`;
      });
      card.addEventListener('pointerleave',()=>card.style.transform='');
    });
  }
})();

(async () => {
  const wrap=document.getElementById('scene'), fallback=document.getElementById('fallback');
  if (!wrap || matchMedia('(prefers-reduced-motion:reduce)').matches) return;
  try {
    const THREE=await import('https://cdn.jsdelivr.net/npm/three@0.180.0/+esm');
    const renderer=new THREE.WebGLRenderer({antialias:true,alpha:true});
    renderer.setPixelRatio(Math.min(devicePixelRatio,1.7)); wrap.prepend(renderer.domElement); fallback.style.display='none';
    const scene=new THREE.Scene(), camera=new THREE.PerspectiveCamera(42,1,.1,100); camera.position.set(0,1.1,7.4);
    scene.add(new THREE.AmbientLight(0xcbd8ce,1.2));
    const cyan=new THREE.PointLight(0x64ddff,17,18); cyan.position.set(3,2,4); scene.add(cyan);
    const violet=new THREE.PointLight(0xa98cff,13,15); violet.position.set(-4,-2,3); scene.add(violet);
    const group=new THREE.Group(); scene.add(group);
    const core=new THREE.Mesh(new THREE.IcosahedronGeometry(1.24,2),new THREE.MeshStandardMaterial({color:0x28342e,metalness:.8,roughness:.27,wireframe:true,emissive:0x142521,emissiveIntensity:.48})); group.add(core);
    const inner=new THREE.Mesh(new THREE.IcosahedronGeometry(.56,1),new THREE.MeshStandardMaterial({color:0x79d8e7,emissive:0x4abccf,emissiveIntensity:1.1,metalness:.25,roughness:.22})); group.add(inner);
    const colors=[0x64ddff,0xa98cff,0xff6db0];
    [1.9,2.35,2.8].forEach((r,i)=>{const ring=new THREE.Mesh(new THREE.TorusGeometry(r,.014,8,180),new THREE.MeshBasicMaterial({color:colors[i],transparent:true,opacity:.52}));ring.rotation.x=Math.PI*(.18+i*.17);ring.rotation.y=i*.55;group.add(ring)});
    for(let i=0;i<12;i++){const a=i/12*Math.PI*2,node=new THREE.Mesh(new THREE.OctahedronGeometry(.095,0),new THREE.MeshBasicMaterial({color:colors[i%3]}));node.position.set(Math.cos(a)*2.35,Math.sin(a*.7)*.85,Math.sin(a)*2.35);group.add(node)}
    const pts=[];for(let i=0;i<500;i++)pts.push((Math.random()-.5)*13,(Math.random()-.5)*8,(Math.random()-.5)*10);const geo=new THREE.BufferGeometry();geo.setAttribute('position',new THREE.Float32BufferAttribute(pts,3));scene.add(new THREE.Points(geo,new THREE.PointsMaterial({color:0x8fa8a4,size:.018,transparent:true,opacity:.5})));
    let px=0,py=0;wrap.addEventListener('pointermove',e=>{const r=wrap.getBoundingClientRect();px=(e.clientX-r.left)/r.width-.5;py=(e.clientY-r.top)/r.height-.5});wrap.addEventListener('pointerleave',()=>{px=py=0});
    function size(){const r=wrap.getBoundingClientRect();renderer.setSize(r.width,r.height,false);camera.aspect=r.width/r.height;camera.updateProjectionMatrix()}addEventListener('resize',size);size();
    const clock=new THREE.Clock();function loop(){const t=clock.getElapsedTime();group.rotation.y=t*.13+px*.36;group.rotation.x=Math.sin(t*.45)*.07-py*.18;inner.scale.setScalar(1+Math.sin(t*2.4)*.055);camera.position.x+=(px*.55-camera.position.x)*.035;camera.position.y+=(1.1-py*.35-camera.position.y)*.035;camera.lookAt(0,0,0);renderer.render(scene,camera);requestAnimationFrame(loop)}loop();
  } catch (err) { console.warn('ARC 3D fallback active',err); }
})();
