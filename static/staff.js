(() => {
  const loginPanel = document.getElementById('loginPanel');
  const workspace = document.getElementById('workspace');
  const loginForm = document.getElementById('loginForm');
  const loginError = document.getElementById('loginError');
  const staffError = document.getElementById('staffError');
  const queueList = document.getElementById('queueList');
  const queueCount = document.getElementById('queueCount');
  const detailPanel = document.getElementById('detailPanel');
  const stateFilter = document.getElementById('stateFilter');
  const logoutButton = document.getElementById('logoutButton');
  const metrics = document.getElementById('metrics');
  const trendChart = document.getElementById('trendChart');
  const dashboardUpdated = document.getElementById('dashboardUpdated');
  let schema = null;
  let outpatientSchema = null;
  let selectedId = '';

  const el = (tag, cls, text) => {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  };
  const call = async (url, options = {}) => {
    const response = await fetch(url, {credentials:'same-origin', ...options});
    const type = response.headers.get('content-type') || '';
    const payload = type.includes('application/json') ? await response.json() : {};
    if (!response.ok) throw new Error(payload.error || 'Không thực hiện được thao tác.');
    return payload;
  };
  const showError = (host, message) => { host.textContent = message; host.hidden = !message; };
  const dateText = value => value ? new Intl.DateTimeFormat('vi-VN',{dateStyle:'short',timeStyle:'short'}).format(new Date(value)) : '—';
  const valueText = (list, value) => list.find(item => String(item.value) === String(value))?.label || String(value || '—');
  const setLoggedIn = loggedIn => {
    loginPanel.hidden = loggedIn;
    workspace.hidden = !loggedIn;
    logoutButton.hidden = !loggedIn;
  };
  const checkSession = async () => {
    try {
      const result = await call('/api/staff/session');
      setLoggedIn(result.authenticated);
      if (result.authenticated) await loadQueue();
    } catch (_) { setLoggedIn(false); }
  };
  const loadDashboard = async () => {
    try {
      const data = await call('/api/staff/dashboard');
      metrics.replaceChildren();
      const items = [
        ['Tổng số phiếu', data.total, 'neutral'],
        ['Phiếu hôm nay', data.today, 'accent'],
        ['Chờ kiểm duyệt', data.counts.pending || 0, 'warning'],
        ['Đã kiểm duyệt', data.counts.approved || 0, 'info'],
        ['Đã gửi BYT', data.counts.sent || 0, 'success'],
        ['Điểm hài lòng TB', data.average_score === null ? '—' : `${data.average_score}/5`, 'score'],
      ];
      for (const [label, value, tone] of items) {
        const card = el('article',`metric metric-${tone}`);
        card.append(el('p','metric-label',label), el('strong','metric-value',String(value)));
        metrics.append(card);
      }
      trendChart.replaceChildren();
      const max = Math.max(1, ...data.daily.map(day=>day.count));
      for (const day of data.daily) {
        const column = el('div','trend-column');
        const bar = el('div','trend-bar'); bar.style.height = `${Math.max(day.count ? 10 : 2, Math.round(day.count * 100 / max))}%`; bar.title = `${day.count} phiếu`;
        const count = el('span','trend-count',String(day.count));
        const label = el('span','trend-label',day.date.slice(5).replace('-','/'));
        column.append(count,bar,label); trendChart.append(column);
      }
      dashboardUpdated.textContent = `Cập nhật ${new Intl.DateTimeFormat('vi-VN',{dateStyle:'short',timeStyle:'short'}).format(new Date())}`;
    } catch (error) {
      dashboardUpdated.textContent = 'Không tải được số liệu';
    }
  };
  const loadQueue = async () => {
    showError(staffError, '');
    queueList.replaceChildren(el('p','empty-queue','Đang tải danh sách…'));
    try {
      const result = await call(`/api/staff/submissions?state=${encodeURIComponent(stateFilter.value)}`);
      queueList.replaceChildren();
      queueCount.textContent = String(result.items.length);
      if (!result.items.length) queueList.append(el('p','empty-queue','Không có phiếu ở trạng thái này.'));
      for (const item of result.items) {
        const button = el('button','queue-item');
        button.type = 'button';
        button.setAttribute('aria-current', item.id === selectedId ? 'true' : 'false');
        button.append(el('span','queue-id',item.id));
        button.append(el('span','',item.patient_name || (item.respondent === '2' ? 'Người nhà trả lời' : 'Người bệnh')));
        button.append(el('span','queue-meta',`Mẫu số ${item.survey_form || '1'} · ${item.ward_label || 'Ngoại trú'} · ${dateText(item.created_at)}`));
        button.addEventListener('click',()=>openDetail(item.id));
        queueList.append(button);
      }
      await loadDashboard();
    } catch (error) {
      if (error.message === 'Đăng nhập lại để tiếp tục.') setLoggedIn(false);
      showError(staffError,error.message);
      queueList.replaceChildren();
    }
  };
  const addPair = (host, label, value) => {
    const dl = el('dl','detail-pair');
    dl.append(el('dt','',label),el('dd','',value || '—'));
    host.append(dl);
  };
  const addSection = (host,title) => {
    const section = el('section','detail-section');
    section.append(el('h3','',title));
    host.append(section);
    return section;
  };
  const addAnswers = (host,questions,ratings) => {
    const list = el('div','answer-list');
    for (const question of questions) {
      const row = el('div','answer-item');
      row.append(el('span','answer-label',`${question.key.toUpperCase()}. ${question.label}`));
      row.append(el('span','answer-value',valueText(schema.scale,ratings[question.key])));
      list.append(row);
    }
    host.append(list);
  };
  const detailActions = item => {
    const actions = el('div','detail-actions');
    if (item.state === 'pending') {
      const approve = el('button','button button-primary','Duyệt phiếu'); approve.type='button'; approve.addEventListener('click',()=>updateState(item.id,'approved')); actions.append(approve);
    } else if (['approved','reviewed','failed'].includes(item.state)) {
      const sent = el('button','button button-primary',item.state==='failed'?'Thử gửi BYT lại':'Gửi BYT'); sent.type='button'; sent.addEventListener('click',()=>{if(window.confirm('Gửi toàn bộ nội dung phiếu này lên cổng Bộ Y tế? Thao tác này sẽ tạo phiếu chính thức.'))sendByt(item.id)}); actions.append(sent);
    }
    if (!['sent','syncing'].includes(item.state)) { const edit=el('button','button button-secondary','Chỉnh sửa phiếu'); edit.type='button'; edit.addEventListener('click',()=>item.survey_form==='2'?renderOutpatientEditor(item):renderEditor(item)); actions.append(edit); }
    return actions;
  };
  const renderOutpatientDetail = item => {
    const profile=item.answers.profile, ratings=item.answers.ratings, s=outpatientSchema;
    detailPanel.replaceChildren(); const head=el('div','detail-head'), title=el('div'); title.append(el('h2','',item.id),el('p','',`Mẫu số 2 · Nhận lúc ${dateText(item.created_at)} · ${item.state_label}`)); head.append(title,el('span',`state-badge ${item.state}`,item.state_label)); detailPanel.append(head,detailActions(item));
    const info=addSection(detailPanel,'Thông tin người bệnh'); const grid=el('div','detail-grid');
    addPair(grid,'Người trả lời',profile.respondent==='2'?'Người nhà':'Người bệnh'); addPair(grid,'Tên bệnh nhân',profile.patient_name); addPair(grid,'Mã bệnh nhân',profile.patient_code); addPair(grid,'Giới tính',valueText([{value:'1',label:'Nam'},{value:'2',label:'Nữ'},{value:'3',label:'Khác'}],profile.gender)); addPair(grid,'Tuổi hoặc năm sinh',profile.age); addPair(grid,'Khoảng cách đến BV',profile.distance ? `${profile.distance} km` : ''); addPair(grid,'BHYT',profile.bhyt==='1'?'Có':'Không'); addPair(grid,'Nơi sinh sống',valueText([{value:'1',label:'Thành thị'},{value:'2',label:'Nông thôn'},{value:'3',label:'Vùng sâu, xa khó khăn'}],profile.residence)); addPair(grid,'Mức sống',valueText([{value:'1',label:'Nghèo'},{value:'2',label:'Cận nghèo'},{value:'3',label:'Khác'}],profile.living_standard)); addPair(grid,'Lần khám',profile.treatment_count); addPair(grid,'Số di động',profile.phone); info.append(grid);
    for(const group of s.groups){const section=addSection(detailPanel,group.title); const list=el('div','answer-list'); for(const question of group.questions){const row=el('div','answer-item');row.append(el('span','answer-label',`${question.key.toUpperCase()}. ${question.label}`),el('span','answer-value',valueText(s.scale,ratings[question.key])));list.append(row)}section.append(list)}
    const outcome=addSection(detailPanel,'E5, F, G và H'); addPair(outcome,'E5. Chi phí',valueText(s.costOptions,ratings.e5_cost)); addPair(outcome,'F1. Đáp ứng mong đợi',ratings.overall_percent ? `${ratings.overall_percent}%`:''); addPair(outcome,'G. Khả năng quay lại',valueText(s.returnOptions,ratings.return_intent)); addPair(outcome,'H1. Lý do chưa hài lòng',ratings.unhappy_detail); addPair(outcome,'H2. Đề xuất',ratings.suggestions);
  };
  const renderDetail = item => {
    if (item.survey_form === '2') { renderOutpatientDetail(item); return; }
    const profile = item.answers.profile;
    const ratings = item.answers.ratings;
    detailPanel.replaceChildren();
    const head = el('div','detail-head');
    const title = el('div');
    title.append(el('h2','',item.id),el('p','',`Nhận lúc ${dateText(item.created_at)} · ${item.state_label}`));
    head.append(title,el('span',`state-badge ${item.state}`,item.state_label));
    detailPanel.append(head);

    const actions = el('div','detail-actions');
    if (item.state === 'pending') {
      const reviewed = el('button','button button-primary','Duyệt phiếu');
      reviewed.type = 'button'; reviewed.addEventListener('click',()=>updateState(item.id,'approved'));
      actions.append(reviewed);
    } else if (item.state === 'approved' || item.state === 'reviewed' || item.state === 'failed') {
      const sent = el('button','button button-primary',item.state === 'failed' ? 'Thử gửi BYT lại' : 'Gửi BYT');
      sent.type = 'button'; sent.addEventListener('click',()=>{
        if (window.confirm('Gửi toàn bộ nội dung phiếu này lên cổng Bộ Y tế? Thao tác này sẽ tạo phiếu chính thức.')) sendByt(item.id);
      });
      actions.append(sent);
    }
    if (!['sent','syncing'].includes(item.state)) {
      const edit = el('button','button button-secondary','Chỉnh sửa phiếu');
      edit.type = 'button'; edit.addEventListener('click',()=>renderEditor(item));
      actions.append(edit);
    }
    detailPanel.append(actions);

    const information = addSection(detailPanel,'Thông tin người bệnh và phiếu');
    const grid = el('div','detail-grid');
    addPair(grid,'Người trả lời',profile.respondent === '2' ? 'Người nhà' : 'Người bệnh');
    addPair(grid,'Tên bệnh nhân',profile.patient_name);
    addPair(grid,'Mã bệnh nhân',profile.patient_code);
    addPair(grid,'Giới tính',valueText([{value:'1',label:'Nam'},{value:'2',label:'Nữ'},{value:'3',label:'Khác'}],profile.gender));
    addPair(grid,'Tuổi hoặc năm sinh',profile.age);
    addPair(grid,'Số di động',profile.phone);
    addPair(grid,'Số ngày nằm viện',profile.stay_days);
    addPair(grid,'BHYT',valueText([{value:'1',label:'Có'},{value:'2',label:'Không'}],profile.bhyt));
    addPair(grid,'Nơi sinh sống',valueText([{value:'1',label:'Thành thị'},{value:'2',label:'Nông thôn'},{value:'3',label:'Vùng sâu, xa khó khăn'}],profile.residence));
    addPair(grid,'Mức sống gia đình',valueText([{value:'1',label:'Nghèo'},{value:'2',label:'Cận nghèo'},{value:'3',label:'Khác'}],profile.living_standard));
    addPair(grid,'Lần điều trị',profile.treatment_count);
    addPair(grid,'Khoa',schema.wards.find(ward=>ward.value===profile.ward)?.label);
    addPair(grid,'Mã khoa',profile.ward_code);
    information.append(grid);

    for (const group of schema.groups) {
      const section = addSection(detailPanel,group.title);
      addAnswers(section,group.questions,ratings);
    }
    const cost = addSection(detailPanel,'E7. Nhận xét về chi phí');
    addPair(cost,'Câu trả lời',valueText(schema.costOptions,ratings.e7));
    if (ratings.cost_other) addPair(cost,'Ý kiến khác',ratings.cost_other);
    const overall = addSection(detailPanel,'G. Đánh giá chung');
    addPair(overall,'G1. Mức độ đáp ứng mong đợi',`${ratings.overall_percent}%`);
    addPair(overall,'G2. Khả năng quay lại hoặc giới thiệu',valueText(schema.returnOptions,ratings.return_intent));
    if (ratings.return_other) addPair(overall,'Ý kiến khác',ratings.return_other);
    const opinions = addSection(detailPanel,'H. Ý kiến');
    addPair(opinions,'H1. Lý do chưa hài lòng',ratings.unhappy_detail);
    addPair(opinions,'H2. Đề xuất',ratings.suggestions);
    addPair(opinions,'Đã đồng ý chuyển dữ liệu',item.consent ? 'Có' : 'Không');
  };
  const optionInput = (host, name, label, options, value) => {
    const wrap = el('label','edit-field');
    wrap.append(el('span','',label));
    const input = document.createElement('select'); input.name = name;
    for (const option of options) {
      const choice = document.createElement('option'); choice.value = String(option.value); choice.textContent = option.label;
      choice.selected = String(option.value) === String(value); input.append(choice);
    }
    wrap.append(input); host.append(wrap);
    return input;
  };
  const textInput = (host, name, label, value, type='text') => {
    const wrap = el('label','edit-field'); wrap.append(el('span','',label));
    const input = type === 'textarea' ? document.createElement('textarea') : document.createElement('input');
    if (type !== 'textarea') input.type = type; input.name = name; input.value = value || '';
    if (type === 'textarea') input.value = value || '';
    wrap.append(input); host.append(wrap); return input;
  };
  const renderOutpatientEditor = item => {
    const profile=item.answers.profile, ratings=item.answers.ratings, s=outpatientSchema;
    detailPanel.replaceChildren(); detailPanel.append(el('h2','',`Chỉnh sửa ${item.id}`),el('p','edit-note','Lưu thay đổi sẽ đưa phiếu về trạng thái chờ kiểm duyệt lại.'));
    const form=el('form','edit-form'), profileSection=addSection(form,'Thông tin người bệnh'), profileGrid=el('div','edit-grid');
    optionInput(profileGrid,'profile.respondent','Người trả lời',[{value:'1',label:'Người bệnh'},{value:'2',label:'Người nhà'}],profile.respondent); textInput(profileGrid,'profile.patient_name','Tên bệnh nhân',profile.patient_name); textInput(profileGrid,'profile.patient_code','Mã bệnh nhân',profile.patient_code); optionInput(profileGrid,'profile.gender','Giới tính',[{value:'1',label:'Nam'},{value:'2',label:'Nữ'},{value:'3',label:'Khác'}],profile.gender); textInput(profileGrid,'profile.age','Tuổi hoặc năm sinh',profile.age,'number'); textInput(profileGrid,'profile.distance','Khoảng cách đến BV (km)',profile.distance,'number'); optionInput(profileGrid,'profile.bhyt','BHYT',[{value:'1',label:'Có'},{value:'2',label:'Không'}],profile.bhyt); optionInput(profileGrid,'profile.residence','Nơi sinh sống',[{value:'1',label:'Thành thị'},{value:'2',label:'Nông thôn'},{value:'3',label:'Vùng sâu, xa khó khăn'}],profile.residence); optionInput(profileGrid,'profile.living_standard','Mức sống',[{value:'1',label:'Nghèo'},{value:'2',label:'Cận nghèo'},{value:'3',label:'Khác'}],profile.living_standard); textInput(profileGrid,'profile.treatment_count','Lần khám',profile.treatment_count,'number'); textInput(profileGrid,'profile.phone','Số di động',profile.phone); profileSection.append(profileGrid);
    for(const group of s.groups){const section=addSection(form,group.title),grid=el('div','edit-grid');for(const question of group.questions)optionInput(grid,`ratings.${question.key}`,`${question.key.toUpperCase()}. ${question.label}`,s.scale,ratings[question.key]);section.append(grid)}
    const outcome=addSection(form,'E5, F, G và H'), outcomeGrid=el('div','edit-grid'); optionInput(outcomeGrid,'ratings.e5_cost','E5. Nhận xét chi phí',s.costOptions,ratings.e5_cost); textInput(outcomeGrid,'ratings.cost_other','E5. Ý kiến khác',ratings.cost_other); textInput(outcomeGrid,'ratings.overall_percent','F1. Đáp ứng mong đợi (%)',ratings.overall_percent,'number'); optionInput(outcomeGrid,'ratings.return_intent','G. Khả năng quay lại',s.returnOptions,ratings.return_intent); textInput(outcomeGrid,'ratings.return_other','G. Ý kiến khác',ratings.return_other); textInput(outcomeGrid,'ratings.unhappy_detail','H1. Lý do chưa hài lòng',ratings.unhappy_detail,'textarea'); textInput(outcomeGrid,'ratings.suggestions','H2. Đề xuất',ratings.suggestions,'textarea'); outcome.append(outcomeGrid);
    const actions=el('div','detail-actions'), cancel=el('button','button button-secondary','Hủy'),save=el('button','button button-primary','Lưu thay đổi');cancel.type='button';save.type='submit';cancel.addEventListener('click',()=>renderOutpatientDetail(item));actions.append(cancel,save);form.append(actions);form.addEventListener('submit',event=>{event.preventDefault();saveEdits(item.id,form)});detailPanel.append(form);
  };
  const renderEditor = item => {
    const profile = item.answers.profile;
    const ratings = item.answers.ratings;
    detailPanel.replaceChildren();
    detailPanel.append(el('h2','',`Chỉnh sửa ${item.id}`), el('p','edit-note','Lưu thay đổi sẽ đưa phiếu về trạng thái chờ kiểm duyệt lại.'));
    const form = el('form','edit-form');
    const profileSection = addSection(form,'Thông tin người bệnh và phiếu');
    const profileGrid = el('div','edit-grid');
    optionInput(profileGrid,'profile.respondent','Người trả lời',[{value:'1',label:'Người bệnh'},{value:'2',label:'Người nhà'}],profile.respondent);
    textInput(profileGrid,'profile.patient_name','Tên bệnh nhân',profile.patient_name);
    textInput(profileGrid,'profile.patient_code','Mã bệnh nhân',profile.patient_code);
    optionInput(profileGrid,'profile.gender','Giới tính',[{value:'1',label:'Nam'},{value:'2',label:'Nữ'},{value:'3',label:'Khác'}],profile.gender);
    textInput(profileGrid,'profile.age','Tuổi hoặc năm sinh',profile.age,'number');
    textInput(profileGrid,'profile.phone','Số di động',profile.phone);
    textInput(profileGrid,'profile.stay_days','Số ngày nằm viện',profile.stay_days,'number');
    optionInput(profileGrid,'profile.bhyt','BHYT',[{value:'1',label:'Có'},{value:'2',label:'Không'}],profile.bhyt);
    optionInput(profileGrid,'profile.residence','Nơi sinh sống',[{value:'1',label:'Thành thị'},{value:'2',label:'Nông thôn'},{value:'3',label:'Vùng sâu, xa khó khăn'}],profile.residence);
    optionInput(profileGrid,'profile.living_standard','Mức sống gia đình',[{value:'1',label:'Nghèo'},{value:'2',label:'Cận nghèo'},{value:'3',label:'Khác'}],profile.living_standard);
    textInput(profileGrid,'profile.treatment_count','Lần điều trị',profile.treatment_count,'number');
    optionInput(profileGrid,'profile.ward','Khoa điều trị',[{value:'',label:'- Không -'},...schema.wards],profile.ward);
    profileSection.append(profileGrid);
    for (const group of schema.groups) {
      const section = addSection(form,group.title);
      const grid = el('div','edit-grid');
      for (const question of group.questions) optionInput(grid,`ratings.${question.key}`,`${question.key.toUpperCase()}. ${question.label}`,schema.scale,ratings[question.key]);
      section.append(grid);
    }
    const overall = addSection(form,'E7, G và H');
    const overallGrid = el('div','edit-grid');
    optionInput(overallGrid,'ratings.e7','E7. Nhận xét về chi phí',schema.costOptions,ratings.e7);
    textInput(overallGrid,'ratings.cost_other','E7. Ý kiến khác',ratings.cost_other);
    textInput(overallGrid,'ratings.overall_percent','G1. Mức độ đáp ứng mong đợi (%)',ratings.overall_percent,'number');
    optionInput(overallGrid,'ratings.return_intent','G2. Khả năng quay lại/giới thiệu',schema.returnOptions,ratings.return_intent);
    textInput(overallGrid,'ratings.return_other','G2. Ý kiến khác',ratings.return_other);
    textInput(overallGrid,'ratings.unhappy_detail','H1. Lý do chưa hài lòng',ratings.unhappy_detail,'textarea');
    textInput(overallGrid,'ratings.suggestions','H2. Đề xuất',ratings.suggestions,'textarea');
    overall.append(overallGrid);
    const actions = el('div','detail-actions');
    const cancel = el('button','button button-secondary','Hủy'); cancel.type='button'; cancel.addEventListener('click',()=>renderDetail(item));
    const save = el('button','button button-primary','Lưu thay đổi'); save.type='submit'; actions.append(cancel,save); form.append(actions);
    form.addEventListener('submit',event=>{ event.preventDefault(); saveEdits(item.id,form); });
    detailPanel.append(form);
  };
  const openDetail = async id => {
    selectedId = id;
    try {
      const result = await call(`/api/staff/submissions/${encodeURIComponent(id)}`);
      renderDetail(result.item);
      await loadQueue();
    } catch (error) { showError(staffError,error.message); }
  };
  const updateState = async (id,nextState) => {
    try {
      await call(`/api/staff/submissions/${encodeURIComponent(id)}/state`,{
        method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({state:nextState})
      });
      await openDetail(id);
    } catch (error) { showError(staffError,error.message); }
  };
  const sendByt = async id => {
    try {
      await call(`/api/staff/submissions/${encodeURIComponent(id)}/send-byt`,{
        method:'POST',headers:{'Content-Type':'application/json'},body:'{}'
      });
      await openDetail(id);
    } catch (error) { showError(staffError,error.message); await loadQueue(); }
  };
  const saveEdits = async (id, form) => {
    const data = new FormData(form);
    const answers = {profile:{},ratings:{}};
    for (const [key,value] of data.entries()) {
      const [group, field] = key.split('.'); answers[group][field] = String(value).trim();
    }
    try {
      await call(`/api/staff/submissions/${encodeURIComponent(id)}/edit`,{
        method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({answers})
      });
      await openDetail(id);
    } catch (error) { showError(staffError,error.message); }
  };
  loginForm.addEventListener('submit',async event=>{
    event.preventDefault(); showError(loginError,'');
    const username = document.getElementById('loginUsername').value.trim();
    const password = document.getElementById('loginPassword').value;
    try {
      await call('/api/staff/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username,password})});
      document.getElementById('loginPassword').value='';
      setLoggedIn(true); await loadQueue();
    } catch (error) { showError(loginError,error.message); }
  });
  logoutButton.addEventListener('click',async()=>{
    await call('/api/staff/logout',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'}).catch(()=>{});
    selectedId='';setLoggedIn(false);loginForm.reset();
  });
  stateFilter.addEventListener('change',()=>loadQueue());
  Promise.all([fetch('/schema.json').then(response=>response.json()),fetch('/schema2.json').then(response=>response.json()),call('/api/staff/session')]).then(([data,outpatient,session])=>{
    schema=data;outpatientSchema=outpatient;setLoggedIn(session.authenticated);if(session.authenticated)loadQueue();
  }).catch(()=>{
    showError(loginError,'Không kết nối được máy chủ review. Vui lòng tải lại trang hoặc báo nhân viên hỗ trợ.');
  });
})();
