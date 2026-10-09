(() => {
  const form = document.getElementById('surveyForm');
  const content = document.getElementById('stepContent');
  const errorBox = document.getElementById('formError');
  const submitButton = document.getElementById('submitButton');
  const state = { profile: {}, ratings: {}, consent: true };
  let schema = null;

  const el = (tag, cls, text) => {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  };
  const sectionHeader = (title, description) => {
    const h = el('h2', 'step-heading', title);
    h.tabIndex = -1;
    content.append(h);
    if (description) content.append(el('p', 'step-description', description));
  };
  const addField = (parent, key, labelText, type, options = {}) => {
    const wrap = el('div', `field${options.full ? ' field-full' : ''}`);
    const label = el('label', '', labelText);
    label.htmlFor = `field-${key}`;
    if (options.required) label.append(el('span', 'required-mark', ' *'));
    const input = document.createElement(type === 'select' ? 'select' : type === 'textarea' ? 'textarea' : 'input');
    input.id = label.htmlFor;
    input.dataset.store = `${options.stateGroup || 'profile'}.${options.stateKey || key}`;
    if (options.readonly) input.readOnly = true;
    if (type !== 'select' && type !== 'textarea') input.type = type;
    if (options.required) input.required = true;
    if (options.min !== undefined) input.min = options.min;
    if (options.max !== undefined) input.max = options.max;
    if (options.step !== undefined) input.step = options.step;
    if (options.maxlength !== undefined) input.maxLength = options.maxlength;
    if (options.placeholder) input.placeholder = options.placeholder;
    if (type === 'select') {
      const blank = el('option', '', options.blank || 'Vui lòng chọn'); blank.value = '';
      input.append(blank);
      for (const option of options.options || []) {
        const node = el('option', '', option.label); node.value = String(option.value); input.append(node);
      }
    }
    if (options.helper) {
      const helper = el('small', 'helper', options.helper);
      helper.id = `${input.id}-helper`;
      input.setAttribute('aria-describedby', helper.id);
      wrap.append(label, input, helper);
    } else wrap.append(label, input);
    input.value = state[options.stateGroup || 'profile'][options.stateKey || key] || '';
    input.addEventListener('input', () => { clearError(); updateProgress(); });
    input.addEventListener('change', updateProgress);
    input.addEventListener('blur', () => validateField(input));
    parent.append(wrap);
    return input;
  };
  const addRadios = (parent, key, labelText, options, required = true, caption = '') => {
    const wrap = el('fieldset', 'field field-full');
    const legend = el('legend', 'field-label', labelText);
    if (required) legend.append(el('span', 'required-mark', ' *'));
    wrap.append(legend);
    const row = el('div', `choice-row ${options.length === 2 ? 'choice-row-2' : 'choice-row-3'}`);
    const chosen = state.profile[key] || '';
    for (const option of options) {
      const label = el('label', 'choice-card');
      const input = document.createElement('input');
      input.type = 'radio'; input.name = `profile-${key}`; input.value = String(option.value); input.dataset.store = `profile.${key}`;
      input.required = required; input.checked = chosen === input.value;
      input.addEventListener('change', () => { clearError(); updateProgress(); });
      label.append(input, el('span', '', option.label)); row.append(label);
    }
    wrap.append(row);
    if (caption) wrap.append(el('small', 'helper', caption));
    parent.append(wrap);
  };
  const renderProfile = () => {
    sectionHeader('Thông tin biểu mẫu', 'Các mục hành chính được bổ sung theo Mẫu số 1 của Bộ Y tế.');
    const meta = el('dl', 'official-meta');
    const addMeta = (label, value) => meta.append(el('dt', '', label), el('dd', '', value));
    addMeta('Kiểu khảo sát', 'Bệnh viện tự đánh giá hàng tháng/quý');
    addMeta('Tên bệnh viện', schema.facility.name);
    addMeta('Mã bệnh viện', schema.facility.code);
    addMeta('Ngày điền phiếu', new Intl.DateTimeFormat('vi-VN').format(new Date()));
    addMeta('3. Người phỏng vấn/điền phiếu', 'a. Người bệnh tự điền (hoặc người nhà)');
    addMeta('Mã số phiếu (do BV quy định)', 'Hệ thống cấp sau khi gửi phiếu');
    content.append(meta);

    const respondentGrid = el('div', 'field-grid');
    addRadios(respondentGrid, 'respondent', '4. Người trả lời', [
      {value:'1',label:'a. Người bệnh'}, {value:'2',label:'b. Người nhà'}
    ]);
    const ward = addField(respondentGrid, 'ward', '5. Khoa nằm điều trị trước ra viện', 'select', {options:schema.wards,blank:'- Không -'});
    const wardCode = addField(respondentGrid, 'ward_code', '6. Mã khoa (do BV ghi)', 'text', {readonly:true,helper:'Mã khoa được điền theo lựa chọn phía trên.'});
    ward.addEventListener('change', () => {
      const item = schema.wards.find(option => option.value === ward.value);
      state.profile.ward_code = item?.code || '';
      wardCode.value = state.profile.ward_code;
    });
    content.append(respondentGrid, el('h3', 'form-subheading', 'THÔNG TIN NGƯỜI BỆNH'));

    const patientGrid = el('div', 'field-grid');
    addField(patientGrid, 'patient_name', 'Tên bệnh nhân', 'text', {maxlength:200,helper:'Có thể nhập tên hoặc 2 ký tự đầu của tên bệnh nhân. Giúp bệnh viện quản lý thông tin. Không bắt buộc.'});
    addField(patientGrid, 'patient_code', 'Mã bệnh nhân', 'text', {maxlength:100});
    addRadios(patientGrid, 'gender', 'A1. Giới tính', [
      {value:'1',label:'1. Nam'}, {value:'2',label:'2. Nữ'}, {value:'3',label:'3. Khác'}
    ]);
    addField(patientGrid, 'age', 'A2. Tuổi hoặc năm sinh', 'number', {required:true,min:0,max:9999,step:1,helper:'Có thể nhập tuổi (0–130) hoặc năm sinh (1900–nay).'});
    addField(patientGrid, 'phone', 'A3. Số di động', 'tel', {required:true,maxlength:30,helper:'Vui lòng nhập số điện thoại để liên hệ khi cần thiết.'});
    addField(patientGrid, 'stay_days', 'A4. Số ngày nằm viện', 'number', {required:true,min:1,max:3650,step:1});
    addRadios(patientGrid, 'bhyt', 'A5. Ông/Bà có sử dụng thẻ BHYT cho lần điều trị này không?', [
      {value:'1',label:'1. Có'}, {value:'2',label:'2. Không'}
    ]);
    addRadios(patientGrid, 'residence', 'A6. Nơi sinh sống hiện nay', [
      {value:'1',label:'1. Thành thị'}, {value:'2',label:'2. Nông thôn'}, {value:'3',label:'3. Vùng sâu, xa khó khăn'}
    ]);
    addRadios(patientGrid, 'living_standard', 'A7. Phân loại mức sống của gia đình', [
      {value:'1',label:'1. Nghèo'}, {value:'2',label:'2. Cận nghèo'}, {value:'3',label:'3. Khác'}
    ]);
    addField(patientGrid, 'treatment_count', 'A8. Đây là lần điều trị thứ mấy của Ông/Bà tại bệnh viện? Lần thứ:', 'number', {required:true,min:1,max:9999,step:1});
    content.append(patientGrid);
  };
  const ratingField = (question) => {
    const fieldset = el('fieldset', 'question');
    const legend = el('legend');
    const number = el('span', 'question-number', `${question.key.toUpperCase()}. `);
    legend.append(number, document.createTextNode(question.label));
    fieldset.append(legend);
    const row = el('div', 'rating-scale');
    const chosen = state.ratings[question.key] || '';
    setRatingState(fieldset, chosen);
    for (const option of schema.scale) {
      const label = el('label', 'rating-option');
      const input = document.createElement('input');
      input.type = 'radio'; input.name = `rating-${question.key}`; input.value = option.value; input.required = true;
      input.dataset.store = `ratings.${question.key}`; input.checked = chosen === option.value;
      input.setAttribute('aria-label', `${option.value}: ${option.label}`);
      input.addEventListener('change', () => { setRatingState(fieldset, input.value); clearError(); updateProgress(); });
      const visual = el('span'); visual.append(document.createTextNode(option.value), el('small', '', option.label));
      label.append(input, visual); row.append(label);
    }
    fieldset.append(row); content.append(fieldset);
  };
  const renderGroup = (group) => {
    sectionHeader(group.title, group.intro);
    content.append(el('p', 'scale-caption', schema.assessmentInstructions));
    const list = el('div', 'question-list');
    for (const question of group.questions) ratingFieldInto(list, question);
    if (group.key === 'e') {
      const fieldset = el('fieldset', 'question');
      const legend = el('legend'); legend.append(el('span','question-number','E7. '),document.createTextNode('Ông/Bà cho nhận xét về số tiền chi trả có tương xứng với chất lượng dịch vụ y tế không?'));
      fieldset.append(legend);
      addRatingChoice(fieldset,'e7',schema.costOptions,state.ratings.e7 || '');
      const other=addField(fieldset,'cost_other','E7. 6. Ý kiến khác, ghi rõ','text',{stateGroup:'ratings',maxlength:1000});
      other.closest('.field').dataset.otherFor='e7'; other.closest('.field').hidden=state.ratings.e7!=='6'; other.required=state.ratings.e7==='6';
      list.append(fieldset);
    }
    content.append(list);
  };
  const ratingFieldInto = (parent, question) => {
    const fieldset = el('fieldset', 'question');
    const legend = el('legend');
    legend.append(el('span', 'question-number', `${question.key.toUpperCase()}. `), document.createTextNode(question.label));
    fieldset.append(legend);
    const row = el('div', 'rating-scale');
    const chosen = state.ratings[question.key] || '';
    setRatingState(fieldset, chosen);
    for (const option of schema.scale) {
      const label = el('label', 'rating-option');
      const input = document.createElement('input');
      input.type = 'radio'; input.name = `rating-${question.key}`; input.value = option.value; input.required = true;
      input.dataset.store = `ratings.${question.key}`; input.checked = chosen === option.value;
      input.setAttribute('aria-label', `${option.value}: ${option.label}`);
      input.addEventListener('change', () => { setRatingState(fieldset, input.value); clearError(); updateProgress(); });
      const visual = el('span'); visual.append(document.createTextNode(option.value), el('small', '', option.label));
      label.append(input, visual); row.append(label);
    }
    fieldset.append(row); parent.append(fieldset);
  };
  const addRatingChoice = (parent, name, options, chosen) => {
    const row = el('div', 'question-list');
    const group = el('div', 'choice-row');
    for (const option of options) {
      const label = el('label', 'choice-card');
      const input = document.createElement('input');
      input.type = 'radio'; input.name = name; input.value = option.value; input.required = true;
      input.dataset.store = `ratings.${name}`; input.checked = chosen === option.value;
      input.addEventListener('change', () => { clearError(); renderConditionalOther(name, input.value); updateProgress(); });
      label.append(input, el('span', '', `${option.value}. ${option.label}`)); group.append(label);
    }
    row.append(group); parent.append(row);
  };
  const renderConditionalOther = (name, value) => {
    const host = content.querySelector(`[data-other-for="${name}"]`);
    if (!host) return;
    host.hidden = value !== '6';
    const field = host.querySelector('input,textarea');
    if (field) field.required = value === '6';
  };
  const renderOutcome = () => {
    sectionHeader('G. Đánh giá chung', 'Đây là cảm nhận tổng thể của Ông/Bà về đợt điều trị vừa qua.');
    const grid = el('div', 'field-grid');
    addField(grid, 'overall_percent', 'G1. Đánh giá chung, bệnh viện đã đáp ứng được bao nhiêu % so với mong đợi của Ông/Bà trước khi nằm viện?', 'number', {required:true,min:0,max:9999,step:1,stateGroup:'ratings',helper:'Điền số từ 0 đến 100 hoặc có thể điền trên 100 nếu bệnh viện điều trị tốt, vượt quá mong đợi của Ông/Bà. Không ghi ký tự % trong ô nhập liệu.'});
    const returnWrap = el('fieldset', 'field field-full');
    const legend = el('legend', 'field-label', 'G2. Nếu có nhu cầu khám, chữa những bệnh, Ông/Bà có quay trở lại hoặc giới thiệu cho người khác đến không?');
    legend.append(el('span','required-mark',' *'));
    returnWrap.append(legend);
    const host = el('div', 'choice-row');
    for (const option of schema.returnOptions) {
      const label = el('label', 'choice-card'); const input = document.createElement('input');
      input.type='radio'; input.name='return_intent'; input.value=option.value; input.required=true;
      input.dataset.store='ratings.return_intent'; input.checked=state.ratings.return_intent===option.value;
      input.addEventListener('change',()=>{clearError();renderConditionalOther('return_intent',input.value);updateProgress();});
      label.append(input,el('span','',`${option.value}. ${option.label}`));host.append(label);
    }
    returnWrap.append(host); grid.append(returnWrap);
    const returnOther = addField(grid, 'return_other', 'G2. Khác (ghi rõ)', 'text', {stateGroup:'ratings',maxlength:1000});
    returnOther.closest('.field').dataset.otherFor='return_intent'; returnOther.closest('.field').hidden=state.ratings.return_intent!=='6'; returnOther.required=state.ratings.return_intent==='6';
    content.append(grid);
    content.append(el('h3', 'form-subheading', 'H. Ý KIẾN'));
    const opinionGrid = el('div', 'field-grid');
    addField(opinionGrid, 'unhappy_detail', 'H1. Đối với các câu hỏi có ý kiến chưa hài lòng, đề nghị Ông/Bà ghi rõ thêm lý do tại sao không hài lòng?', 'textarea', {stateGroup:'ratings',maxlength:3000,full:true});
    addField(opinionGrid, 'suggestions', 'H2. Ông/Bà có ý kiến hoặc nhận xét gì khác giúp bệnh viện và hệ thống khám, chữa bệnh phục vụ người bệnh được tốt hơn, xin ghi rõ?', 'textarea', {stateGroup:'ratings',maxlength:3000,full:true});
    content.append(opinionGrid);
  };
  const RATING_TOTAL = 37;
  const renderForm = () => {
    content.replaceChildren(); errorBox.hidden = true;
    renderProfile();
    for (const group of schema.groups) renderGroup(group);
    renderOutcome();
    updateProgress();
  };
  const collectCurrent = () => {
    for (const input of content.querySelectorAll('[data-store]')) {
      const key = input.dataset.store;
      if (input.type === 'radio') {
        if (!input.checked) continue;
        const [group, property] = key.split('.'); state[group][property] = input.value;
      } else if (input.type === 'checkbox') {
        state.consent = input.checked;
      } else {
        const [group, property] = key.split('.'); state[group][property] = input.value.trim();
      }
    }
  };
  const clearError = () => { errorBox.hidden = true; errorBox.textContent = ''; };
  const setRatingState = (fieldset, value) => {
    fieldset.classList.remove('rating-state-0', 'rating-state-1', 'rating-state-2', 'rating-state-3', 'rating-state-4', 'rating-state-5');
    if (/^[0-5]$/.test(value || '')) fieldset.classList.add(`rating-state-${value}`);
  };
  const validateField = (input) => {
    if (input.checkValidity()) input.removeAttribute('aria-invalid');
    else input.setAttribute('aria-invalid','true');
  };
  const validateActive = () => {
    collectCurrent();
    const required = [...content.querySelectorAll('[required]')].filter(input => !input.closest('[hidden]'));
    const invalid = required.find(input => !input.checkValidity());
    if (invalid) {
      errorBox.textContent = 'Vui lòng hoàn tất các mục có dấu * trên phiếu.';
      errorBox.hidden = false;
      invalid.setAttribute('aria-invalid','true'); invalid.focus();
      return false;
    }
    return true;
  };
  const updateProgress = () => {};
  const readApiResponse = async response => {
    const body = await response.text();
    try { return JSON.parse(body); }
    catch (_) { throw new Error('Không thể kết nối máy chủ khảo sát. Vui lòng kiểm tra mạng và thử gửi lại.'); }
  };
  form.addEventListener('submit',async event=>{
    event.preventDefault();
    if (!validateActive()) return;
    submitButton.disabled=true; submitButton.textContent='Đang gửi lên Bộ Y tế…';
    try {
      const response = await fetch('/api/submissions',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(state)});
      const result = await readApiResponse(response);
      if (!response.ok) throw new Error(result.error || 'Chưa lưu được phiếu. Vui lòng báo nhân viên hỗ trợ.');
      form.hidden=true;
      const success=el('section','success-panel');success.setAttribute('role','status');
      success.append(el('div','success-mark','✓'),el('h2','','Cảm ơn Ông/Bà đã chia sẻ'));
      success.append(el('p','',result.submitted ? 'Phiếu đã được gửi thành công lên cổng khảo sát Bộ Y tế.' : `Phiếu đã lưu với mã tham chiếu. ${result.message || 'Hệ thống chưa xác nhận được việc gửi lên Bộ Y tế.'}`));
      const code=el('div','receipt-code',result.id);code.setAttribute('aria-label',`Mã phiếu ${result.id}`);success.append(code);
      document.querySelector('.survey-frame').append(success);
      window.scrollTo({top:0,behavior:'smooth'});
    } catch (error) {
      errorBox.textContent=error.message;errorBox.hidden=false;submitButton.disabled=false;submitButton.textContent='Gửi đi';
      errorBox.scrollIntoView({behavior:'smooth',block:'center'});
    }
  });
  fetch('/schema.json').then(response=>response.json()).then(data=>{schema=data;for(const group of schema.groups)for(const question of group.questions)state.ratings[question.key] ??= '3';document.getElementById('officialIntro').textContent=data.officialIntro;renderForm();}).catch(()=>{
    errorBox.textContent='Không tải được biểu mẫu. Vui lòng tải lại trang hoặc báo nhân viên hỗ trợ.';errorBox.hidden=false;
  });
})();
