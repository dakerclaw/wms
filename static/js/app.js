// ===================== 工具函数 =====================
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
  if (id === 'page-inbound') initIbPage();
  if (id === 'page-outbound') initObPage();
  if (id === 'page-inbound-query') initIbQueryPage();
  if (id === 'page-outbound-query') initObQueryPage();
}

async function api(method, url, body) {
  const opts = {
    method,
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include'
  };
  if (body) opts.body = JSON.stringify(body);
  const res = await fetch(url, opts);
  return res.json();
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

// ===================== 入库 =====================
let ibItems = [];

function initIbPage() {
  ibItems = [];
  document.getElementById('ib-factory').value = '';
  renderIbTable();
  addIbRow(); // 默认一行
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
      <td data-row="2"><input type="text" value="${escHtml(item.batch_no)}" onchange="ibItems[${i}].batch_no=this.value" placeholder="物料批号"></td>
      <td data-row="3"><input type="text" value="${escHtml(item.equipment)}" onchange="ibItems[${i}].equipment=this.value" placeholder="设备"></td>
      <td data-row="3"><input type="text" value="${escHtml(item.package_no)}" onchange="ibItems[${i}].package_no=this.value" placeholder="包号"></td>
      <td data-row="3"><input type="number" step="0.01" value="${item.weight}" onchange="ibItems[${i}].weight=parseFloat(this.value)||0" placeholder="质量(kg)"></td>
      <td data-row="1"><button class="btn btn-danger btn-sm" onclick="removeIbRow(${i})">删</button></td>
    </tr>
  `).join('');
}

function addIbRow() {
  const last = ibItems[ibItems.length - 1];
  let newPkg = '';
  if (last && last.package_no) {
    const num = parseInt(last.package_no);
    newPkg = isNaN(num) ? last.package_no : String(num + 1);
  }
  ibItems.push({
    batch_no: last ? last.batch_no : '',
    equipment: last ? last.equipment : '',
    package_no: newPkg,
    weight: last ? last.weight : ''
  });
  renderIbTable();
  setTimeout(() => {
    const rows = document.getElementById('ib-tbody').querySelectorAll('tr');
    if (rows.length > 0) {
      const lastRow = rows[rows.length - 1];
      const inputs = lastRow.querySelectorAll('input');
      if (inputs.length > 0) inputs[ibItems.length === 1 ? 0 : 1].focus();
    }
  }, 50);
}

function removeIbRow(i) {
  ibItems.splice(i, 1);
  renderIbTable();
}

function previewInbound() {
  const factory = document.getElementById('ib-factory').value;
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
  const factory = document.getElementById('ib-factory').value;
  const line = ibItems[0].equipment.trim();
  const res = await api('POST', '/api/inbound', {
    factory, equipment: line, items: ibItems
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

function initIbQueryPage() {
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

function initObPage() {
  obItems = [];
  document.getElementById('ob-factory').value = '';
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
      <td data-row="2"><input type="text" value="${escHtml(item.batch_no)}" onchange="obItems[${i}].batch_no=this.value" placeholder="物料批号"></td>
      <td data-row="3"><input type="text" value="${escHtml(item.equipment)}" onchange="obItems[${i}].equipment=this.value" placeholder="设备"></td>
      <td data-row="3"><input type="text" value="${escHtml(item.package_no)}" onchange="obItems[${i}].package_no=this.value" placeholder="包号"></td>
      <td data-row="3"><input type="number" step="0.01" value="${item.weight}" onchange="obItems[${i}].weight=parseFloat(this.value)||0" placeholder="质量(kg)"></td>
      <td data-row="1"><button class="btn btn-danger btn-sm" onclick="removeObRow(${i})">删</button></td>
    </tr>
  `).join('');
}

function addObRow() {
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
    if (rows.length > 0) {
      const lastRow = rows[rows.length - 1];
      const inputs = lastRow.querySelectorAll('input');
      if (inputs.length > 0) inputs[0].focus();
    }
  }, 50);
}

function removeObRow(i) {
  obItems.splice(i, 1);
  renderObTable();
}

function previewOutbound() {
  const factory = document.getElementById('ob-factory').value;
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
  const factory = document.getElementById('ob-factory').value;
  const trip = document.getElementById('ob-trip').value.trim();
  const res = await api('POST', '/api/outbound', { factory, trip, items: obItems });
  if (res.code === 200) {
    closeObConfirm();
    showToast(`出库成功！单号：${res.order_no}`, 'success', 4000);
    initObPage();
    showPage('page-menu');
  } else {
    showToast(res.msg || '提交失败', 'error');
  }
}

// ===================== 出库查询 =====================
let lastObQueryData = [];
let lastObOrderMap = {};  // order_no -> { order info + items[] }

function initObQueryPage() {
  const el = document.getElementById('oq-date');
  if (el && !el.value) {
    const now = new Date();
    const y = now.getFullYear();
    const m = String(now.getMonth() + 1).padStart(2, '0');
    const d = String(now.getDate()).padStart(2, '0');
    el.value = `${y}-${m}-${d}`;
  }
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
        ${u.username !== 'shangtai' ? `<button class="btn btn-danger btn-sm" style="margin-left:6px;" onclick="deleteUser(${u.id},'${escHtml(u.username)}')">删除</button>` : ''}
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
