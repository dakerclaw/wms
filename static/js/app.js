// ===================== 工具函数 =====================

// 全局厂区缓存
let _factories = [];
let _factoriesLoaded = false;






function showToast(msg, type = 'success', duration = 2500) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = 'toast show ' + type;
  setTimeout(() => { t.className = 'toast'; }, duration);
}

function showPage(id) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.getElementById(id).classList.add('active');
  // 进入账号管理时加载列表
  if (id === 'page-user-manage') loadUsers();
  if (id === 'page-factory-manage') loadFactories();
  if (id === 'page-inbound') initIbPage();
  if (id === 'page-outbound') initObPage();
  if (id === 'page-inbound-query') initIbQueryPage();
  if (id === 'page-outbound-query') initObQueryPage();
  if (id === 'page-overview') loadOverview();
}

// ===================== 厂区公共加载 =====================

async function loadFactoriesCache() {
  if (_factoriesLoaded) return _factories;
  try {
    const res = await api('GET', '/api/factories');
    if (res.code === 200) {
      _factories = res.data || [];
      _factoriesLoaded = true;
    }
  } catch (e) {
    console.error('加载厂区失败', e);
  }
  // 兜底：如果接口失败，使用默认值
  if (_factories.length === 0) {
    _factories = [{ id: 1, name: '3号厂房', sort_order: 1 }, { id: 2, name: '10号厂房', sort_order: 2 }];
    _factoriesLoaded = true;
  }
  return _factories;
}

function invalidateFactoriesCache() {
  _factoriesLoaded = false;
  _factories = [];
}

/** 渲染 radio 组（入库/出库页面用） */
function renderFactoryRadio(containerId, radioName, checkedName) {
  const container = document.getElementById(containerId);
  if (!container) return;
  const factories = _factories;
  container.innerHTML = factories.map((f, i) => `
    <label class="radio-label">
      <input type="radio" name="${radioName}" value="${escHtml(f.name)}" ${i === 0 || f.name === checkedName ? 'checked' : ''}> ${escHtml(f.name)}
    </label>
  `).join('');
}

/** 渲染 select 下拉（入库/出库查询用） */
function renderFactorySelect(selectId) {
  const sel = document.getElementById(selectId);
  if (!sel) return;
  // 保留第一个 option（"全部"）
  const firstOpt = sel.options[0];
  sel.innerHTML = '';
  sel.appendChild(firstOpt);
  _factories.forEach(f => {
    const opt = document.createElement('option');
    opt.value = f.name;
    opt.textContent = f.name;
    sel.appendChild(opt);
  });
}

async function api(method, url, body) {
  const opts = {
    method,
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include'
  };
  if (body) opts.body = JSON.stringify(body);
  // GET 请求加时间戳参数防止浏览器缓存返回旧数据
  if (!body && url.includes('?')) {
    url += '&_t=' + Date.now();
  } else if (!body) {
    url += '?_t=' + Date.now();
  }
  const res = await fetch(url, opts);
  try {
    return await res.json();
  } catch (e) {
    // 服务器返回非 JSON（如 HTML 错误页），统一包装成标准错误对象
    return { code: res.status, msg: `服务器错误 (${res.status})` };
  }
}

// ===================== 登录 =====================
async function doLogin() {
  const username = document.getElementById('login-username').value.trim();
  const password = document.getElementById('login-password').value.trim();
  if (!username || !password) { showToast('请输入用户名和密码', 'error'); return; }
  const res = await api('POST', '/api/login', { username, password });
  if (res.code === 200) {
    showToast('登录成功', 'success');
    document.getElementById('nav-username').textContent = '👤 ' + res.username;
    document.getElementById('navbar').style.display = '';
    // 管理员显示账号管理菜单
    document.getElementById('admin-menu-card').style.display = res.role === 'admin' ? '' : 'none';
    showPage('page-menu');
    // 清空登录框
    document.getElementById('login-username').value = '';
    document.getElementById('login-password').value = '';
  } else {
    showToast(res.msg, 'error');
  }
}

async function logout() {
  await api('POST', '/api/logout');
  document.getElementById('navbar').style.display = 'none';
  showPage('page-login');
  showToast('已退出登录');
}

// 检查登录状态
async function checkSession() {
  const res = await api('GET', '/api/me');
  if (res.code === 200) {
    document.getElementById('nav-username').textContent = '👤 ' + res.user;
    document.getElementById('navbar').style.display = '';
    document.getElementById('admin-menu-card').style.display = res.role === 'admin' ? '' : 'none';
    showPage('page-menu');
  }
}

// ===================== 数据概览 =====================
async function loadOverview() {
  // 重置为加载状态
  document.getElementById('overview-time-tip').textContent = '加载中…';
  ['ov-ib-pkg','ov-ib-weight','ov-ob-trip','ov-ob-pkg','ov-ob-weight'].forEach(id => {
    document.getElementById(id).textContent = '…';
  });
  document.getElementById('ov-ib-tbody').innerHTML = '<tr><td colspan="4" class="no-data">加载中…</td></tr>';
  document.getElementById('ov-ob-tbody').innerHTML = '<tr><td colspan="4" class="no-data">加载中…</td></tr>';

  function overviewError(msg) {
    document.getElementById('overview-time-tip').textContent = msg;
    ['ov-ib-pkg','ov-ib-weight','ov-ob-trip','ov-ob-pkg','ov-ob-weight'].forEach(id => {
      document.getElementById(id).textContent = '—';
    });
    document.getElementById('ov-ib-tbody').innerHTML = `<tr><td colspan="4" class="no-data">${msg}</td></tr>`;
    document.getElementById('ov-ob-tbody').innerHTML = `<tr><td colspan="4" class="no-data">${msg}</td></tr>`;
  }

  try {
    const res = await api('GET', '/api/overview');
    if (res.code === 403) {
      overviewError('无权限：仅管理员可查看概览数据');
      return;
    }
    if (res.code !== 200) {
      overviewError(res.msg || '数据加载失败，请刷新重试');
      showToast(res.msg || '概览数据加载失败', 'error');
      return;
    }

    // 时间范围提示
    document.getElementById('overview-time-tip').innerHTML =
      `📥 入库统计区间：<strong>${res.ib_start}</strong> ~ <strong>${res.ib_end}</strong>&nbsp;&nbsp;` +
      `📤 出库统计日期：<strong>${res.ob_date}</strong>`;

    // 汇总数字
    document.getElementById('ov-ib-pkg').textContent    = res.ib_total.pkg_count;
    document.getElementById('ov-ib-weight').textContent = res.ib_total.total_weight ?? 0;
    document.getElementById('ov-ob-trip').textContent   = res.ob_total.trip_count;
    document.getElementById('ov-ob-pkg').textContent    = res.ob_total.pkg_count;
    document.getElementById('ov-ob-weight').textContent = res.ob_total.total_weight ?? 0;

    // 入库明细表
    const ibTbody = document.getElementById('ov-ib-tbody');
    if (!res.inbound.length) {
      ibTbody.innerHTML = '<tr><td colspan="4" class="no-data">该时段暂无入库记录</td></tr>';
    } else {
      ibTbody.innerHTML = res.inbound.map(r => `
        <tr>
          <td>${escHtml(r.equipment)}</td>
          <td>${escHtml(r.batch_no)}</td>
          <td><strong>${r.pkg_count}</strong></td>
          <td><strong>${r.total_weight}</strong></td>
        </tr>
      `).join('');
    }

    // 出库明细表
    const obTbody = document.getElementById('ov-ob-tbody');
    if (!res.outbound.length) {
      obTbody.innerHTML = '<tr><td colspan="4" class="no-data">今日暂无出库记录</td></tr>';
    } else {
      obTbody.innerHTML = res.outbound.map(r => `
        <tr>
          <td>${escHtml(r.factory)}</td>
          <td>${escHtml(r.trip)}</td>
          <td><strong>${r.pkg_count}</strong></td>
          <td><strong>${r.total_weight}</strong></td>
        </tr>
      `).join('');
    }
  } catch (e) {
    overviewError('请求失败，请检查网络后重试');
    showToast('请求失败，请重试', 'error');
  }
}

// ===================== 入库 =====================
let ibItems = [];

async function initIbPage() {
  ibItems = [];
  await loadFactoriesCache();
  renderFactoryRadio('ib-factory-group', 'ib-factory');
  // 包装形式默认选中标包
  document.getElementById('ib-pkgtype-std').checked = true;
  renderIbTable();
  addIbRow(); // 默认一行
}

// 通用函数：同步 tbody 中所有 input 的当前值到数组（防止手机端 oninput 未及时触发）
function syncCurrentInputs(tbodyId, items) {
  const tbody = document.getElementById(tbodyId);
  const rows = tbody.querySelectorAll('tr');
  rows.forEach((tr, i) => {
    if (i >= items.length) return;
    const inputs = tr.querySelectorAll('input');
    // 直接按 input 顺序同步到数组对应字段
    if (inputs[0]) items[i].batch_no = inputs[0].value;
    if (inputs[1]) items[i].equipment = inputs[1].value;   // 正整数字符串
    if (inputs[2]) items[i].package_no = inputs[2].value;  // 正整数字符串
    if (inputs[3]) items[i].weight = parseFloat(inputs[3].value) || 0;
  });
}

function renderIbTable() {
  const tbody = document.getElementById('ib-tbody');
  if (ibItems.length === 0) {
    tbody.innerHTML = '<tr><td colspan="5" class="no-data" style="padding:20px;text-align:center;color:#bbb;">暂无数据，请添加物料</td></tr>';
    return;
  }
  tbody.innerHTML = ibItems.map((item, i) => `
    <tr>
      <td class="td-no" data-row="1">${i + 1}</td>
      <td data-row="2"><input type="text" value="${escHtml(item.batch_no)}" oninput="ibItems[${i}].batch_no=this.value" placeholder="物料批号"></td>
      <td data-row="3"><input type="text" inputmode="numeric" pattern="[0-9]*" value="${escHtml(item.equipment)}" oninput="this.value=this.value.replace(/[^0-9]/g,'');ibItems[${i}].equipment=this.value" placeholder="设备"></td>
      <td data-row="3"><input type="text" inputmode="numeric" pattern="[0-9]*" value="${escHtml(item.package_no)}" oninput="this.value=this.value.replace(/[^0-9]/g,'');ibItems[${i}].package_no=this.value" placeholder="包号"></td>
      <td data-row="3"><input type="number" step="any" min="0" value="${item.weight||''}" oninput="ibItems[${i}].weight=parseFloat(this.value)||0" placeholder="质量(kg)"></td>
      <td data-row="1"><button class="btn btn-danger btn-sm" onclick="removeIbRow(${i})">删</button></td>
    </tr>
  `).join('');
}

function addIbRow() {
  // 添加行前先同步当前所有 input 的值到数组（防止手机端 oninput 未及时触发）
  syncCurrentInputs('ib-tbody', ibItems);

  const last = ibItems[ibItems.length - 1];
  const pkgType = document.querySelector('input[name="ib-package-type"]:checked')?.value || '标包';

  let newPkg = '';
  if (last && last.package_no) {
    const num = parseInt(last.package_no);
    newPkg = isNaN(num) ? last.package_no : String(num + 1);
  }

  if (pkgType === '非标包') {
    ibItems.push({
      batch_no: last ? last.batch_no : '',
      equipment: last ? last.equipment : '',
      package_no: newPkg,
      weight: ''
    });
  } else {
    ibItems.push({
      batch_no: last ? last.batch_no : '',
      equipment: last ? last.equipment : '',
      package_no: newPkg,
      weight: last ? last.weight : ''
    });
  }

  renderIbTable();

  setTimeout(() => {
    const rows = document.getElementById('ib-tbody').querySelectorAll('tr');
    const lastRow = rows[rows.length - 1];
    const inputs = lastRow.querySelectorAll('input');
    if (inputs.length > 0) {
      const focusIdx = pkgType === '非标包' ? 3 : (ibItems.length === 1 ? 0 : 1);
      inputs[Math.min(focusIdx, inputs.length - 1)].focus();
    }
  }, 50);
}

function removeIbRow(i) {
  syncCurrentInputs('ib-tbody', ibItems);
  ibItems.splice(i, 1);
  renderIbTable();
}

function previewInbound() {
  const factory = document.querySelector('input[name="ib-factory"]:checked')?.value || '';
  const pkgType = document.querySelector('input[name="ib-package-type"]:checked')?.value || '';
  if (!factory) { showToast('请选择厂区', 'error'); return; }
  if (ibItems.length === 0) { showToast('请至少录入一行物料', 'error'); return; }
  // 验证所有行
  for (let i = 0; i < ibItems.length; i++) {
    if (!ibItems[i].batch_no.trim()) { showToast(`第${i + 1}行批号不能为空`, 'error'); return; }
    if (!ibItems[i].equipment.trim()) { showToast(`第${i + 1}行设备不能为空`, 'error'); return; }
    if (!ibItems[i].package_no.toString().trim()) { showToast(`第${i + 1}行包号不能为空`, 'error'); return; }
    if (!ibItems[i].weight || ibItems[i].weight <= 0) { showToast(`第${i + 1}行质量须大于0`, 'error'); return; }
  }

  // 取第一行的设备作为主设备显示
  const line = ibItems[0].equipment.trim();

  // 生成预览单号（使用本地时间，与后端一致）
  const now = new Date();
  const pad = (n, l) => String(n).padStart(l || 2, '0');
  const preview = 'RK' + now.getFullYear() + pad(now.getMonth()+1) + pad(now.getDate())
    + pad(now.getHours()) + pad(now.getMinutes()) + pad(now.getSeconds()) + pad(now.getMilliseconds(), 3);
  document.getElementById('ib-order-no-preview').textContent = preview;
  document.getElementById('ib-confirm-factory').textContent = factory;
  document.getElementById('ib-confirm-line').textContent = line;
  document.getElementById('ib-confirm-pkgtype').textContent = pkgType;

  const tbody = document.getElementById('ib-confirm-tbody');
  let totalWeight = 0;
  tbody.innerHTML = ibItems.map((item, i) => {
    const listNo = `${item.batch_no}-${item.equipment}-${item.package_no}`;
    totalWeight += (item.weight || 0);
    return `<tr><td>${i + 1}</td><td>${escHtml(listNo)}</td><td>${item.weight}</td></tr>`;
  }).join('');
  document.getElementById('ib-confirm-total').textContent = ibItems.length;
  document.getElementById('ib-confirm-weight').textContent = totalWeight.toFixed(2);

  document.getElementById('ib-confirm-overlay').classList.add('show');
}

function closeIbConfirm() {
  document.getElementById('ib-confirm-overlay').classList.remove('show');
}

async function submitInbound() {
  const factory = document.querySelector('input[name="ib-factory"]:checked')?.value || '';
  const pkgType = document.querySelector('input[name="ib-package-type"]:checked')?.value || '';
  const line = ibItems[0].equipment.trim();
  const res = await api('POST', '/api/inbound', {
    factory, equipment: line, package_type: pkgType, items: ibItems
  });
  if (res.code === 200) {
    closeIbConfirm();
    showToast(`入库成功！单号：${res.order_no}`, 'success', 4000);
    initIbPage();
    showPage('page-menu');
  } else {
    showToast(res.msg || '提交失败', 'error');
  }
}

// ===================== 入库查询 =====================
let lastIbQueryData = [];

async function initIbQueryPage() {
  // 默认：昨日8:00 ~ 今日8:00
  const today = new Date();
  today.setHours(8, 0, 0, 0);
  const yesterday = new Date(today);
  yesterday.setDate(yesterday.getDate() - 1);
  const fmt = (d) => {
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, '0');
    const dd = String(d.getDate()).padStart(2, '0');
    const h = String(d.getHours()).padStart(2, '0');
    const mi = String(d.getMinutes()).padStart(2, '0');
    return `${y}-${m}-${dd}T${h}:${mi}`;
  };
  document.getElementById('iq-start').value = fmt(yesterday);
  document.getElementById('iq-end').value = fmt(today);
  await loadFactoriesCache();
  renderFactorySelect('iq-factory');
}

async function queryInbound() {
  const params = new URLSearchParams({
    date_start: document.getElementById('iq-start').value.replace('T', ' '),
    date_end: document.getElementById('iq-end').value.replace('T', ' '),
    factory: document.getElementById('iq-factory').value,
    equipment: document.getElementById('iq-line').value,
    batch_no: document.getElementById('iq-batch').value
  });
  const res = await api('GET', '/api/inbound/query?' + params);
  const tbody = document.getElementById('iq-tbody');
  if (res.code !== 200 || !res.data.length) {
    tbody.innerHTML = '<tr><td colspan="8" class="no-data">暂无数据</td></tr>';
    document.getElementById('iq-count').textContent = '';
    lastIbQueryData = [];
    return;
  }
  lastIbQueryData = res.data;
  document.getElementById('iq-count').textContent = `共 ${res.data.length} 条`;
  tbody.innerHTML = res.data.map(r => `
    <tr>
      <td class="pc-only">${escHtml(r.order_no)}</td>
      <td class="pc-only">${r.created_at}</td>
      <td class="pc-only">${escHtml(r.factory)}</td>
      <td class="pc-only">${escHtml(r.equipment)}</td>
      <td>${r.seq}</td>
      <td>${escHtml(r.list_no)}</td>
      <td>${r.weight}</td>
      <td class="pc-only">${escHtml(r.operator)}</td>
    </tr>
  `).join('');
}

function exportInbound() {
  if (!lastIbQueryData.length) { showToast('暂无数据可导出，请先查询', 'error'); return; }
  const headers = ['入库单号', '入库时间', '厂区', '设备', '序号', '清单包号', '重量(kg)', '操作员'];
  const rows = lastIbQueryData.map(r => [r.order_no, r.created_at, r.factory, r.equipment, r.seq, r.list_no, r.weight, r.operator]);
  const now = new Date().toISOString().slice(0, 10);
  downloadXLSX(`入库查询_${now}.xlsx`, headers, rows);
  showToast('导出成功', 'success');
}

// ===================== 出库 =====================
let obItems = [];

async function initObPage() {
  obItems = [];
  await loadFactoriesCache();
  renderFactoryRadio('ob-factory-group', 'ob-factory');
  document.getElementById('ob-trip').value = '';
  renderObTable();
  addObRow();
}

function renderObTable() {
  const tbody = document.getElementById('ob-tbody');
  if (obItems.length === 0) {
    tbody.innerHTML = '<tr><td colspan="6" class="no-data" style="padding:20px;text-align:center;color:#bbb;">暂无数据，请添加物料</td></tr>';
    return;
  }
  tbody.innerHTML = obItems.map((item, i) => `
    <tr>
      <td class="td-no" data-row="1">${i + 1}</td>
      <td data-row="2"><input type="text" value="${escHtml(item.batch_no)}" oninput="obItems[${i}].batch_no=this.value" placeholder="物料批号"></td>
      <td data-row="3"><input type="text" inputmode="numeric" pattern="[0-9]*" value="${escHtml(item.equipment)}" oninput="this.value=this.value.replace(/[^0-9]/g,'');obItems[${i}].equipment=this.value" placeholder="设备"></td>
      <td data-row="3"><input type="text" inputmode="numeric" pattern="[0-9]*" value="${escHtml(item.package_no)}" oninput="this.value=this.value.replace(/[^0-9]/g,'');obItems[${i}].package_no=this.value" placeholder="包号"></td>
      <td data-row="3"><input type="number" step="any" min="0" value="${item.weight||''}" oninput="obItems[${i}].weight=parseFloat(this.value)||0" placeholder="质量(kg)"></td>
      <td data-row="1"><button class="btn btn-danger btn-sm" onclick="removeObRow(${i})">删</button></td>
    </tr>
  `).join('');
}

function addObRow() {
  syncCurrentInputs('ob-tbody', obItems);

  const last = obItems[obItems.length - 1];
  obItems.push({
    batch_no: last ? last.batch_no : '',
    equipment: last ? last.equipment : '',
    package_no: '',
    weight: last ? last.weight : ''
  });

  renderObTable();

  setTimeout(() => {
    const rows = document.getElementById('ob-tbody').querySelectorAll('tr');
    const lastRow = rows[rows.length - 1];
    const inputs = lastRow.querySelectorAll('input');
    if (inputs.length > 2) inputs[2].focus();
    else if (inputs.length > 0) inputs[0].focus();
  }, 50);
}

function removeObRow(i) {
  syncCurrentInputs('ob-tbody', obItems);
  obItems.splice(i, 1);
  renderObTable();
}

function previewOutbound() {
  const factory = document.querySelector('input[name="ob-factory"]:checked')?.value || '';
  const trip = document.getElementById('ob-trip').value.trim();
  if (!factory) { showToast('请选择厂区', 'error'); return; }
  if (!trip) { showToast('请输入车次', 'error'); return; }
  if (obItems.length === 0) { showToast('请至少录入一行物料', 'error'); return; }
  for (let i = 0; i < obItems.length; i++) {
    if (!obItems[i].batch_no.trim()) { showToast(`第${i + 1}行批号不能为空`, 'error'); return; }
    if (!obItems[i].equipment.trim()) { showToast(`第${i + 1}行设备不能为空`, 'error'); return; }
    if (!obItems[i].package_no.toString().trim()) { showToast(`第${i + 1}行包号不能为空`, 'error'); return; }
    if (!obItems[i].weight || obItems[i].weight <= 0) { showToast(`第${i + 1}行质量须大于0`, 'error'); return; }
  }

  const now = new Date();
  const pad = (n, l) => String(n).padStart(l || 2, '0');
  const preview = 'CK' + now.getFullYear() + pad(now.getMonth()+1) + pad(now.getDate())
    + pad(now.getHours()) + pad(now.getMinutes()) + pad(now.getSeconds()) + pad(now.getMilliseconds(), 3);
  document.getElementById('ob-order-no-preview').textContent = preview;
  document.getElementById('ob-confirm-factory').textContent = factory;
  document.getElementById('ob-confirm-trip').textContent = trip;

  const tbody = document.getElementById('ob-confirm-tbody');
  let totalWeight = 0;
  tbody.innerHTML = obItems.map((item, i) => {
    const listNo = `${item.batch_no}-${item.equipment}-${item.package_no}`;
    totalWeight += (item.weight || 0);
    return `<tr><td>${i + 1}</td><td>${escHtml(listNo)}</td><td>${item.weight}</td></tr>`;
  }).join('');
  document.getElementById('ob-confirm-total').textContent = obItems.length;
  document.getElementById('ob-confirm-weight').textContent = totalWeight.toFixed(2);

  document.getElementById('ob-confirm-overlay').classList.add('show');
}

function closeObConfirm() {
  document.getElementById('ob-confirm-overlay').classList.remove('show');
}

async function submitOutbound() {
  const factory = document.querySelector('input[name="ob-factory"]:checked')?.value || '';
  const trip = document.getElementById('ob-trip').value.trim();

  // 先校验库存
  const checkRes = await api('POST', '/api/outbound/check', { items: obItems });
  if (checkRes.code !== 200) {
    showToast(checkRes.msg || '库存校验失败', 'error');
    return;
  }

  if (checkRes.no_stock_count > 0) {
    // 有无库存条目，弹窗提醒
    const tbody = document.getElementById('ob-no-stock-tbody');
    tbody.innerHTML = checkRes.no_stock.map(item => {
      const listNo = item.list_no || `${item.batch_no}-${item.equipment}-${item.package_no}`;
      const reason = checkRes.in_stock.length === 0 ? '未入库或已出库' : '未入库或已出库';
      return `<tr><td>${escHtml(listNo)}</td><td style="color:#ff4d4f;">${reason}</td></tr>`;
    }).join('');

    const tip = document.getElementById('ob-stock-warn-tip');
    if (checkRes.in_stock_count > 0) {
      tip.innerHTML = `有库存：<strong style="color:#52c41a;">${checkRes.in_stock_count} 条</strong>，无库存：<strong style="color:#ff4d4f;">${checkRes.no_stock_count} 条</strong>。点击下方按钮可仅出库有库存的条目。`;
      document.getElementById('ob-stock-warn-ok').style.display = '';
    } else {
      tip.innerHTML = `<strong style="color:#ff4d4f;">所有条目均无库存</strong>，无法出库，请检查物料录入是否正确。`;
      document.getElementById('ob-stock-warn-ok').style.display = 'none';
    }

    document.getElementById('ob-stock-warn-overlay').classList.add('show');
    return;
  }

  // 全部有库存，直接提交
  await doSubmitOutbound();
}

function closeObStockWarn() {
  document.getElementById('ob-stock-warn-overlay').classList.remove('show');
}

async function doSubmitOutbound() {
  closeObStockWarn();
  const factory = document.querySelector('input[name="ob-factory"]:checked')?.value || '';
  const trip = document.getElementById('ob-trip').value.trim();
  const res = await api('POST', '/api/outbound', { factory, trip, items: obItems });
  if (res.code === 200) {
    closeObConfirm();
    let msg = `出库成功！单号：${res.order_no}`;
    if (res.no_stock_count > 0) {
      msg += `\n（${res.no_stock_count} 条无库存已跳过）`;
    }
    showToast(msg, 'success', 5000);
    initObPage();
    showPage('page-menu');
  } else {
    showToast(res.msg || '提交失败', 'error');
  }
}

// ===================== 出库查询 =====================
let lastObQueryData = [];
let lastObOrderMap = {};  // order_no -> { order info + items[] }

async function initObQueryPage() {
  const el = document.getElementById('oq-date');
  if (el && !el.value) {
    const now = new Date();
    const y = now.getFullYear();
    const m = String(now.getMonth() + 1).padStart(2, '0');
    const d = String(now.getDate()).padStart(2, '0');
    el.value = `${y}-${m}-${d}`;
  }
  await loadFactoriesCache();
  renderFactorySelect('oq-factory');
}

async function queryOutbound() {
  const params = new URLSearchParams({
    date: document.getElementById('oq-date').value,
    factory: document.getElementById('oq-factory').value,
    trip: document.getElementById('oq-trip').value,
    batch_no: document.getElementById('oq-batch').value
  });
  const res = await api('GET', '/api/outbound/query?' + params);
  const tbody = document.getElementById('oq-tbody');
  if (res.code !== 200 || !res.data.length) {
    tbody.innerHTML = '<tr><td colspan="8" class="no-data">暂无数据</td></tr>';
    document.getElementById('oq-count').textContent = '';
    lastObQueryData = [];
    lastObOrderMap = {};
    return;
  }
  lastObQueryData = res.data;

  // 按出库单号汇总
  const orderMap = {};
  res.data.forEach(r => {
    if (!orderMap[r.order_no]) {
      orderMap[r.order_no] = {
        order_no: r.order_no,
        created_at: r.created_at,
        factory: r.factory,
        trip: r.trip,
        operator: r.operator,
        items: [],
        totalWeight: 0
      };
    }
    orderMap[r.order_no].items.push(r);
    orderMap[r.order_no].totalWeight += (r.weight || 0);
  });
  lastObOrderMap = orderMap;

  const orderList = Object.values(orderMap);
  document.getElementById('oq-count').textContent = `共 ${orderList.length} 单`;
  tbody.innerHTML = orderList.map(o => `
    <tr>
      <td><span class="order-link" onclick="showObDetail('${escHtml(o.order_no)}')">${escHtml(o.order_no)}</span></td>
      <td>${o.created_at}</td>
      <td>${escHtml(o.factory)}</td>
      <td>${escHtml(o.trip)}</td>
      <td>${o.items.length}</td>
      <td>${o.totalWeight.toFixed(2)}</td>
      <td>${escHtml(o.operator)}</td>
      <td><button class="btn btn-primary btn-sm" onclick="showObDetail('${escHtml(o.order_no)}')">详情</button></td>
    </tr>
  `).join('');
}

function exportOutbound() {
  if (!lastObQueryData.length) { showToast('暂无数据可导出，请先查询', 'error'); return; }
  const headers = ['出库单号', '出库时间', '厂区', '车次', '物料批号', '设备', '包号', '清单包号', '重量(kg)', '操作员'];
  const rows = lastObQueryData.map(r => [r.order_no, r.created_at, r.factory, r.trip, r.batch_no, r.equipment, r.package_no, r.list_no, r.weight, r.operator]);
  const now = new Date().toISOString().slice(0, 10);
  downloadXLSX(`出库查询_${now}.xlsx`, headers, rows);
  showToast('导出成功', 'success');
}

function showObDetail(orderNo) {
  const order = lastObOrderMap[orderNo];
  if (!order) return;
  document.getElementById('ob-detail-order-no').textContent = order.order_no;
  document.getElementById('ob-detail-factory').textContent = order.factory;
  document.getElementById('ob-detail-trip').textContent = order.trip;
  document.getElementById('ob-detail-operator').textContent = order.operator;
  document.getElementById('ob-detail-time').textContent = order.created_at;
  document.getElementById('ob-detail-total').textContent = order.items.length;
  document.getElementById('ob-detail-weight').textContent = order.totalWeight.toFixed(2);

  const tbody = document.getElementById('ob-detail-tbody');
  tbody.innerHTML = order.items.map((item, i) => `
    <tr>
      <td>${i + 1}</td>
      <td class="pc-only">${escHtml(item.batch_no)}</td>
      <td class="pc-only">${escHtml(item.equipment)}</td>
      <td class="pc-only">${escHtml(item.package_no)}</td>
      <td>${escHtml(item.list_no)}</td>
      <td>${item.weight}</td>
    </tr>
  `).join('');

  document.getElementById('ob-detail-overlay').classList.add('show');
}

function closeObDetail() {
  document.getElementById('ob-detail-overlay').classList.remove('show');
}

function exportOutboundDetail() {
  const orderNo = document.getElementById('ob-detail-order-no').textContent;
  const order = lastObOrderMap[orderNo];
  if (!order || !order.items.length) { showToast('无数据可导出', 'error'); return; }
  const headers = ['序号', '物料批号', '设备', '包号', '清单包号', '重量(kg)'];
  const rows = order.items.map((item, i) => [i + 1, item.batch_no, item.equipment, item.package_no, item.list_no, item.weight]);
  downloadXLSX(`出库单_${orderNo}.xlsx`, headers, rows);
  showToast('导出成功', 'success');
}

// ===================== 厂区管理 =====================

async function loadFactories() {
  const res = await api('GET', '/api/factories');
  const tbody = document.getElementById('fm-tbody');
  if (res.code !== 200) {
    tbody.innerHTML = '<tr><td colspan="5" class="no-data">加载失败</td></tr>';
    return;
  }
  _factories = res.data || [];
  _factoriesLoaded = true;
  if (_factories.length === 0) {
    tbody.innerHTML = '<tr><td colspan="5" class="no-data">暂无厂区数据</td></tr>';
    return;
  }
  tbody.innerHTML = _factories.map(f => `
    <tr>
      <td>${f.id}</td>
      <td>${escHtml(f.name)}</td>
      <td>${f.sort_order}</td>
      <td>${f.created_at || ''}</td>
      <td>
        <button class="btn btn-primary btn-sm" onclick="openEditFactory(${f.id},'${escHtml(f.name)}',${f.sort_order})">改</button>
        <button class="btn btn-danger btn-sm" onclick="deleteFactory(${f.id},'${escHtml(f.name)}')">删</button>
      </td>
    </tr>
  `).join('');
}

async function addFactory() {
  const name = document.getElementById('fm-name').value.trim();
  const order = parseInt(document.getElementById('fm-order').value) || 0;
  if (!name) { showToast('请输入厂区名称', 'error'); return; }
  const res = await api('POST', '/api/factories', { name, sort_order: order });
  if (res.code === 200) {
    showToast('添加成功');
    document.getElementById('fm-name').value = '';
    document.getElementById('fm-order').value = '0';
    invalidateFactoriesCache();
    loadFactories();
  } else {
    showToast(res.msg || '添加失败', 'error');
  }
}

function openEditFactory(id, name, order) {
  document.getElementById('edit-fid').value = id;
  document.getElementById('edit-fname').value = name;
  document.getElementById('edit-forder').value = order;
  document.getElementById('edit-factory-overlay').classList.add('show');
}

function closeEditFactory() {
  document.getElementById('edit-factory-overlay').classList.remove('show');
}

async function saveEditFactory() {
  const id = document.getElementById('edit-fid').value;
  const name = document.getElementById('edit-fname').value.trim();
  const order = parseInt(document.getElementById('edit-forder').value) || 0;
  if (!name) { showToast('厂区名称不能为空', 'error'); return; }
  const res = await api('PUT', `/api/factories/${id}`, { name, sort_order: order });
  if (res.code === 200) {
    showToast('修改成功');
    closeEditFactory();
    invalidateFactoriesCache();
    loadFactories();
  } else {
    showToast(res.msg || '修改失败', 'error');
  }
}

function deleteFactory(id, name) {
  showGenericConfirm('删除厂区', `确认删除厂区「${name}」？此操作不可撤销。`, '确认删除', async function() {
    const res = await api('DELETE', `/api/factories/${id}`);
    if (res.code === 200) {
      showToast('删除成功');
      invalidateFactoriesCache();
      loadFactories();
    } else {
      showToast(res.msg || '删除失败', 'error');
    }
  });
}

// ===================== 账号管理 =====================
async function loadUsers() {
  const res = await api('GET', '/api/users');
  const tbody = document.getElementById('um-tbody');
  if (res.code !== 200) {
    tbody.innerHTML = `<tr><td colspan="5" class="no-data">${res.msg || '加载失败'}</td></tr>`;
    return;
  }
  if (!res.data.length) {
    tbody.innerHTML = '<tr><td colspan="5" class="no-data">暂无账号</td></tr>';
    return;
  }
  tbody.innerHTML = res.data.map(u => `
    <tr>
      <td>${u.id}</td>
      <td>${escHtml(u.username)}</td>
      <td><span class="${u.role === 'admin' ? 'tag-admin' : 'tag-user'}">${u.role === 'admin' ? '管理员' : '普通用户'}</span></td>
      <td>${u.created_at}</td>
      <td>
        <button class="btn btn-warning btn-sm" onclick="openEditUser(${u.id},'${escHtml(u.username)}','${u.role}')">修改</button>
        ${u.username !== 'admin' ? `<button class="btn btn-danger btn-sm" style="margin-left:6px;" onclick="deleteUser(${u.id},'${escHtml(u.username)}')">删除</button>` : ''}
      </td>
    </tr>
  `).join('');
}

async function addUser() {
  const username = document.getElementById('um-username').value.trim();
  const password = document.getElementById('um-password').value.trim();
  const role = document.getElementById('um-role').value;
  if (!username || !password) { showToast('用户名和密码不能为空', 'error'); return; }
  const res = await api('POST', '/api/users', { username, password, role });
  if (res.code === 200) {
    showToast('添加成功', 'success');
    document.getElementById('um-username').value = '';
    document.getElementById('um-password').value = '';
    loadUsers();
  } else {
    showToast(res.msg, 'error');
  }
}

function openEditUser(id, username, role) {
  document.getElementById('edit-uid').value = id;
  document.getElementById('edit-uname').value = username;
  document.getElementById('edit-pwd').value = '';
  document.getElementById('edit-role').value = role;
  document.getElementById('edit-user-overlay').classList.add('show');
}

function closeEditUser() {
  document.getElementById('edit-user-overlay').classList.remove('show');
}

async function saveEditUser() {
  const uid = document.getElementById('edit-uid').value;
  const password = document.getElementById('edit-pwd').value.trim();
  const role = document.getElementById('edit-role').value;
  const res = await api('PUT', `/api/users/${uid}`, { password, role });
  if (res.code === 200) {
    showToast('修改成功', 'success');
    closeEditUser();
    loadUsers();
  } else {
    showToast(res.msg, 'error');
  }
}

async function deleteUser(id, username) {
  showGenericConfirm('删除账号', `确认删除账号「${username}」？此操作不可撤销。`, '确认删除', async function() {
    const res = await api('DELETE', `/api/users/${id}`);
    if (res.code === 200) {
      showToast('删除成功', 'success');
      loadUsers();
    } else {
      showToast(res.msg, 'error');
    }
  });
}

// ===================== 导入/导出账号 =====================
async function exportUsers() {
  try {
    showToast('正在导出...', 'success');
    const res = await api('GET', '/api/users');
    if (!res || res.code !== 200) { showToast((res && res.msg) || '导出失败', 'error'); return; }
    const headers = ['用户名', '角色', '创建时间'];
    const rows = res.data.map(u => [u.username, u.role === 'admin' ? '管理员' : '普通用户', u.created_at]);
    // 手动拼 CSV
    let csv = '\ufeff' + headers.join(',') + '\n';
    rows.forEach(r => { csv += r.map(v => '"' + v + '"').join(',') + '\n'; });
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'users_export.csv';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    showToast('导出成功', 'success');
  } catch (e) {
    showToast('导出失败：' + e.message, 'error');
  }
}

function openImportUsers() {
  document.getElementById('import-users-file').value = '';
  document.getElementById('import-users-overlay').classList.add('show');
}

function closeImportUsers() {
  document.getElementById('import-users-overlay').classList.remove('show');
}

async function doImportUsers() {
  const fileInput = document.getElementById('import-users-file');
  if (!fileInput.files.length) { showToast('请选择 CSV 文件', 'error'); return; }
  const formData = new FormData();
  formData.append('file', fileInput.files[0]);
  try {
    const res = await fetch(window.location.origin + '/api/users/import', {
      method: 'POST',
      body: formData,
      credentials: 'include'
    });
    if (!res.ok) {
      const text = await res.text();
      showToast('导入失败(HTTP ' + res.status + ')：' + text.substring(0, 200), 'error');
      return;
    }
    const text = await res.text();
    let data;
    try {
      data = JSON.parse(text);
    } catch (je) {
      showToast('返回数据格式错误：' + text.substring(0, 200), 'error');
      return;
    }
    if (data.code === 200) {
      closeImportUsers();
      let msg = data.msg;
      if (data.errors && data.errors.length) {
        msg += '\n' + data.errors.join('\n');
      }
      showToast(msg, 'success');
      loadUsers();
    } else {
      showToast(data.msg, 'error');
    }
  } catch (e) {
    showToast('导入失败：' + e.message, 'error');
  }
}

// ===================== 通用确认弹窗 =====================
let genericConfirmCallback = null;

function showGenericConfirm(title, msg, okText, callback) {
  document.getElementById('generic-confirm-title').textContent = title;
  document.getElementById('generic-confirm-msg').textContent = msg;
  const okBtn = document.getElementById('generic-confirm-ok');
  okBtn.textContent = okText || '确认';
  genericConfirmCallback = callback;
  okBtn.onclick = function() {
    const cb = genericConfirmCallback;
    closeGenericConfirm();
    if (cb) cb();
  };
  document.getElementById('generic-confirm-overlay').classList.add('show');
}

function closeGenericConfirm() {
  document.getElementById('generic-confirm-overlay').classList.remove('show');
  genericConfirmCallback = null;
}

// ===================== 数据清理 =====================
function openCleanModal() {
  // 重置弹窗状态
  document.getElementById('clean-date').value = '';
  document.getElementById('clean-preview').style.display = 'none';
  document.getElementById('clean-empty').style.display = 'none';
  document.getElementById('clean-confirm-btn').style.display = 'none';
  document.getElementById('clean-overlay').classList.add('show');
}

function closeCleanModal() {
  document.getElementById('clean-overlay').classList.remove('show');
}

async function previewClean() {
  const date = document.getElementById('clean-date').value;
  if (!date) { showToast('请先选择日期', 'error'); return; }

  // 隐藏之前的结果
  document.getElementById('clean-preview').style.display = 'none';
  document.getElementById('clean-empty').style.display = 'none';
  document.getElementById('clean-confirm-btn').style.display = 'none';

  try {
    const res = await fetch(`/api/records/preview?before_date=${encodeURIComponent(date)}`);
    const data = await res.json();
    if (data.code !== 200) { showToast(data.msg, 'error'); return; }

    if (data.inbound === 0 && data.outbound === 0) {
      document.getElementById('clean-empty').style.display = 'block';
    } else {
      document.getElementById('clean-ib-count').textContent = data.inbound;
      document.getElementById('clean-ob-count').textContent = data.outbound;
      document.getElementById('clean-preview').style.display = 'block';
      document.getElementById('clean-confirm-btn').style.display = '';
    }
  } catch (e) {
    showToast('请求失败，请重试', 'error');
  }
}

async function doClean() {
  const date = document.getElementById('clean-date').value;
  if (!date) { showToast('请先选择日期', 'error'); return; }

  const ibCount = document.getElementById('clean-ib-count').textContent;
  const obCount = document.getElementById('clean-ob-count').textContent;

  // 二次确认
  showGenericConfirm(
    '确认删除',
    `将删除 ${date} 之前的记录：\n入库单 ${ibCount} 条，出库单 ${obCount} 条\n\n此操作不可撤销！`,
    '确认删除',
    async function() {
      try {
        const res = await fetch('/api/records/delete', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ before_date: date })
        });
        const data = await res.json();
        if (data.code === 200) {
          showToast(data.msg, 'success');
          closeCleanModal();
        } else {
          showToast(data.msg || '删除失败', 'error');
        }
      } catch (e) {
        showToast('请求失败，请重试', 'error');
      }
    }
  );
}

// ===================== 数据库备份管理 =====================
let backupFilterDate = '';  // 当前查询筛选日期

function openBackupModal() {
  backupFilterDate = '';
  document.getElementById('backup-query-date').value = '';
  document.getElementById('backup-delete-btn').style.display = 'none';
  document.getElementById('backup-result-tip').style.display = 'none';
  document.getElementById('backup-list-title').textContent = '现有备份文件';
  document.getElementById('backup-overlay').classList.add('show');
  loadBackupList();
}

function closeBackupModal() {
  document.getElementById('backup-overlay').classList.remove('show');
}

function _formatSize(bytes) {
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / 1024 / 1024).toFixed(2) + ' MB';
}

function _renderBackupList(list) {
  const wrap = document.getElementById('backup-list-wrap');
  if (!list || list.length === 0) {
    wrap.innerHTML = '<div style="text-align:center;color:#bbb;padding:24px 0;font-size:13px;">没有匹配的备份文件</div>';
    return;
  }
  let html = '<table style="width:100%;border-collapse:collapse;font-size:13px;">';
  html += '<thead><tr style="background:#f5f5f5;">' +
    '<th style="padding:8px 10px;text-align:left;font-weight:600;">文件名</th>' +
    '<th style="padding:8px 10px;text-align:center;font-weight:600;">备份时间</th>' +
    '<th style="padding:8px 10px;text-align:right;font-weight:600;">大小</th>' +
    '</tr></thead><tbody>';
  list.forEach((f, i) => {
    const bg = i % 2 === 0 ? '#fff' : '#fafafa';
    html += '<tr style="background:' + bg + ';">' +
      '<td style="padding:7px 10px;color:#555;">' + f.filename + '</td>' +
      '<td style="padding:7px 10px;text-align:center;color:#333;">' + f.display + '</td>' +
      '<td style="padding:7px 10px;text-align:right;color:#888;">' + _formatSize(f.size) + '</td>' +
      '</tr>';
  });
  html += '</tbody></table>';
  wrap.innerHTML = html;
}

async function loadBackupList() {
  const wrap = document.getElementById('backup-list-wrap');
  wrap.innerHTML = '<div style="text-align:center;color:#bbb;padding:24px 0;font-size:13px;">加载中…</div>';
  try {
    const res = await fetch('/api/backup/list');
    const data = await res.json();
    if (data.code !== 200) { wrap.innerHTML = '<div style="color:#ff4d4f;padding:12px;">获取列表失败</div>'; return; }
    _renderBackupList(data.data);
  } catch (e) {
    wrap.innerHTML = '<div style="color:#ff4d4f;padding:12px;">请求失败，请重试</div>';
  }
}

async function queryBackupList() {
  const date = document.getElementById('backup-query-date').value;
  if (!date) { showToast('请先选择日期', 'error'); return; }
  backupFilterDate = date;

  const wrap = document.getElementById('backup-list-wrap');
  const tip = document.getElementById('backup-result-tip');
  wrap.innerHTML = '<div style="text-align:center;color:#bbb;padding:24px 0;font-size:13px;">查询中…</div>';
  tip.style.display = 'none';
  document.getElementById('backup-delete-btn').style.display = 'none';

  try {
    const res = await fetch('/api/backup/list');
    const data = await res.json();
    if (data.code !== 200) { wrap.innerHTML = '<div style="color:#ff4d4f;padding:12px;">查询失败</div>'; return; }

    const cutoff = date.replaceAll('-', '');
    const filtered = (data.data || []).filter(f => f.date <= cutoff);

    document.getElementById('backup-list-title').textContent = date + ' 之前的备份';

    if (filtered.length === 0) {
      tip.style.display = 'block';
      tip.style.background = '#f6ffed';
      tip.style.border = '1px solid #b7eb8f';
      tip.innerHTML = '✅ ' + date + ' 之前没有备份文件';
      document.getElementById('backup-delete-btn').style.display = 'none';
    } else {
      tip.style.display = 'block';
      tip.style.background = '#fff7e6';
      tip.style.border = '1px solid #ffd591';
      tip.innerHTML = '查询到 <strong>' + filtered.length + '</strong> 个备份文件';
      document.getElementById('backup-delete-btn').style.display = '';
    }
    _renderBackupList(filtered);
  } catch (e) {
    wrap.innerHTML = '<div style="color:#ff4d4f;padding:12px;">请求失败，请重试</div>';
  }
}

async function doCreateBackup() {
  const btn = document.getElementById('backup-create-btn');
  btn.disabled = true;
  btn.textContent = '备份中…';
  try {
    const res = await fetch('/api/backup/create', { method: 'POST', headers: { 'Content-Type': 'application/json' } });
    const data = await res.json();
    if (data.code === 200) {
      showToast(data.msg, 'success');
      // 如果当前有查询筛选，刷新查询结果；否则刷新全部列表
      if (backupFilterDate) {
        queryBackupList();
      } else {
        loadBackupList();
      }
    } else {
      showToast(data.msg || '备份失败', 'error');
    }
  } catch (e) {
    showToast('请求失败，请重试', 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = '立即备份';
  }
}

async function doDeleteBackups() {
  if (!backupFilterDate) { showToast('请先查询备份', 'error'); return; }
  showGenericConfirm('确认删除', '确认删除查询结果中的所有备份文件？\n此操作不可撤销！', '确认删除', async function() {
    try {
      const res = await fetch('/api/backup/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ before_date: backupFilterDate })
      });
      const data = await res.json();
      if (data.code === 200) {
        showToast(data.msg, 'success');
        queryBackupList();
      } else {
        showToast(data.msg || '删除失败', 'error');
      }
    } catch (e) {
      showToast('请求失败，请重试', 'error');
    }
  });
}

// ===================== XSS防护 =====================
function escHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

// ===================== Excel 导出工具 =====================
function downloadXLSX(filename, headers, rows) {
  const data = [headers, ...rows];
  const ws = XLSX.utils.aoa_to_sheet(data);
  // 设置列宽
  ws['!cols'] = headers.map(() => ({ wch: 18 }));
  const wb = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(wb, ws, 'Sheet1');
  XLSX.writeFile(wb, filename);
}

// ===================== 初始化 =====================
window.onload = function () {
  checkSession();
  // 所有文本输入框输入时自动转大写（排除用户名输入框）
  document.addEventListener('input', function(e) {
    if (e.target.tagName === 'INPUT' && e.target.type === 'text' && !e.target.classList.contains('no-uppercase')) {
      const pos = e.target.selectionStart;
      const val = e.target.value.toUpperCase();
      if (val !== e.target.value) {
        e.target.value = val;
        e.target.setSelectionRange(pos, pos);
      }
    }
  });
};
