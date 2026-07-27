const HOSTNAME = window.location.hostname || '100.97.230.66';
const API_BASE = `http://${HOSTNAME}:5555`;
const PORT5000_BASE = `http://${HOSTNAME}:5000`;

let currentSubnet = 'ALL';
let currentSearch = '';
let allDevicesData = [];
let activeModalDeviceId = null;
let modalStreamInterval = null;
let gridApi = null;

document.addEventListener('DOMContentLoaded', () => {
    initAgGrid();
    fetchDevices();
    setInterval(fetchDevices, 2000);
});

function initAgGrid() {
    const columnDefs = [
        { 
            headerName: '단말기 ID', 
            field: 'device_id', 
            width: 145, 
            pinned: 'left',
            cellRenderer: p => `<strong>📱 ${p.value}</strong>`
        },
        { 
            headerName: 'LTE 서브넷', 
            field: 'subnet', 
            width: 115, 
            cellRenderer: p => `<span class="subnet-tag">lte${p.value}</span>`
        },
        { 
            headerName: '할당 LTE IP', 
            field: 'real_ip', 
            width: 145, 
            cellRenderer: p => (p.value && p.value !== '-') ? `<code style="color: var(--neon-green);">${p.value}</code>` : '-'
        },
        { 
            headerName: '관제 상태 / 진행 단계', 
            field: 'step', 
            width: 180, 
            cellRenderer: p => {
                let badgeClass = 'badge-idle';
                if (p.data.is_running) badgeClass = 'badge-running';
                else if (p.value.includes('COOLDOWN') || p.value.includes('PENALTY')) badgeClass = 'badge-cooldown';
                return `<span class="badge ${badgeClass}">${p.value}</span>`;
            }
        },
        { 
            headerName: 'Task ID (회차)', 
            field: 'task_id', 
            width: 170, 
            cellRenderer: p => (p.value && p.value !== '-') ? `<code>#${p.value}</code> <span style="font-size: 0.72rem; color: var(--neon-blue);">(회차 #${p.data.device_seq || '-'})</span>` : '-'
        },
        { 
            headerName: '목적지 명칭 (ID)', 
            field: 'destination', 
            minWidth: 220,
            flex: 1,
            cellRenderer: p => (p.value && p.value !== '-') ? `<strong>${p.value}</strong> <span style="font-size: 0.72rem; color: var(--text-muted);">(ID: ${p.data.dest_id || '-'})</span>` : '-'
        },
        { 
            headerName: '최근 반응 시간', 
            field: 'last_active', 
            width: 135,
            cellRenderer: p => `<code>${p.value || '-'}</code>`
        },
        {
            headerName: '개별 제어 및 라이브 검사',
            field: 'actions',
            width: 250,
            pinned: 'right',
            sortable: false,
            filter: false,
            cellRenderer: p => {
                const devId = p.data.device_id;
                return `
                    <div style="display: flex; gap: 0.3rem; justify-content: center; align-items: center; height: 100%;">
                        <button class="btn btn-primary btn-sm" title="화면 검사 팝업" onclick="openScreenModal('${devId}')">📺 화면보기</button>
                        <button class="btn btn-warning btn-sm" title="즉시 재시작" onclick="controlDevice('${devId}', 'restart')">🔄</button>
                        <button class="btn btn-danger btn-sm" title="강제 중지" onclick="controlDevice('${devId}', 'stop')">🛑</button>
                        <button class="btn btn-sm" title="작업 유예" onclick="controlDevice('${devId}', 'pause')">⏸</button>
                        <button class="btn btn-success btn-sm" title="작업 재개" onclick="controlDevice('${devId}', 'start')">▶</button>
                    </div>
                `;
            }
        }
    ];

    const gridOptions = {
        columnDefs: columnDefs,
        rowData: [],
        defaultColDef: {
            sortable: true,
            filter: true,
            resizable: true
        },
        animateRows: true,
        pagination: true,
        paginationPageSize: 100,
        suppressRowClickSelection: true,
        enableCellTextSelection: true
    };

    const gridDiv = document.querySelector('#myGrid');
    gridApi = agGrid.createGrid(gridDiv, gridOptions);
}

async function fetchDevices() {
    try {
        const res = await fetch(`${API_BASE}/api/v1/devices`);
        const data = await res.json();
        
        if (data.status === 'ok') {
            allDevicesData = data.devices;
            updateStats(data.stats);
            renderDeviceTable();
            if (activeModalDeviceId) {
                updateModalInfo();
            }
        }
    } catch (err) {
        console.error('Error fetching devices:', err);
    }
}

function updateStats(stats) {
    document.getElementById('stat-total').innerText = stats.total;
    document.getElementById('stat-running').innerText = stats.running;
    document.getElementById('stat-idle').innerText = stats.idle;
    document.getElementById('stat-cooldown').innerText = stats.cooldown;
}

function filterSubnet(subnet, element) {
    currentSubnet = subnet;
    document.querySelectorAll('.subnet-chip').forEach(el => el.classList.remove('active'));
    if (element) element.classList.add('active');
    renderDeviceTable();
}

function onSearchChange() {
    currentSearch = document.getElementById('device-search').value.toLowerCase().trim();
    if (gridApi) {
        gridApi.setGridOption('quickFilterText', currentSearch);
    }
}

function getFilteredDevices() {
    return allDevicesData.filter(dev => {
        const devSubnetStr = `lte${dev.subnet}`;
        const matchesSubnet = (currentSubnet === 'ALL') || (devSubnetStr === currentSubnet) || (String(dev.subnet) === currentSubnet.replace('lte',''));
        return matchesSubnet;
    });
}

function renderDeviceTable() {
    if (!gridApi) return;
    const filteredData = getFilteredDevices();
    gridApi.setGridOption('rowData', filteredData);
}

/* SCREEN INSPECTION MODAL HANDLERS */
function openScreenModal(deviceId) {
    activeModalDeviceId = deviceId;
    const dev = allDevicesData.find(d => d.device_id === deviceId);
    if (!dev) return;

    document.getElementById('modal-dev-id').innerText = `단말기: ${dev.device_id}`;
    document.getElementById('modal-subnet').innerText = `lte${dev.subnet}`;
    
    const port5000Btn = document.getElementById('modal-port5000-link');
    if (port5000Btn) {
        port5000Btn.href = `${PORT5000_BASE}/`;
    }

    updateModalInfo();

    const modalImg = document.getElementById('modal-screen-img');
    const ts = new Date().getTime();
    modalImg.src = `${API_BASE}/api/v1/screen/${deviceId}?t=${ts}`;

    if (modalStreamInterval) clearInterval(modalStreamInterval);
    modalStreamInterval = setInterval(() => {
        if (!activeModalDeviceId) return;
        const now = new Date().getTime();
        const preloader = new Image();
        preloader.onload = () => {
            modalImg.src = `${API_BASE}/api/v1/screen/${activeModalDeviceId}?t=${now}`;
        };
        preloader.src = `${API_BASE}/api/v1/screen/${activeModalDeviceId}?t=${now}`;
    }, 1500);

    document.getElementById('screen-modal').classList.add('active');
}

function closeScreenModal(event) {
    if (event && event.target !== document.getElementById('screen-modal') && !event.target.classList.contains('modal-close-btn')) {
        return;
    }
    activeModalDeviceId = null;
    if (modalStreamInterval) clearInterval(modalStreamInterval);
    document.getElementById('screen-modal').classList.remove('active');
}

function updateModalInfo() {
    if (!activeModalDeviceId) return;
    const dev = allDevicesData.find(d => d.device_id === activeModalDeviceId);
    if (!dev) return;

    document.getElementById('modal-step').innerText = dev.step;
    document.getElementById('modal-task-id').innerText = `#${dev.task_id} (회차 #${dev.device_seq || '-'})`;
    document.getElementById('modal-dest').innerText = dev.destination !== '-' ? `${dev.destination} (ID: ${dev.dest_id})` : '-';
    document.getElementById('modal-ip').innerText = dev.real_ip || '-';
    document.getElementById('modal-active-time').innerText = dev.last_active || '-';
}

async function modalControlAction(action) {
    if (!activeModalDeviceId) return;
    await controlDevice(activeModalDeviceId, action);
}

async function controlDevice(deviceId, action) {
    if (!confirm(`단말기 [${deviceId}]에 대해 '${action.toUpperCase()}' 제어를 실행하시겠습니까?`)) return;

    try {
        const res = await fetch(`${API_BASE}/api/v1/device/control`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ device_id: deviceId, action: action })
        });
        const data = await res.json();
        alert(`단말기 ${deviceId}: ${action.toUpperCase()} -> ${data.result || '성공'}`);
        fetchDevices();
    } catch (err) {
        alert('제어 실행 실패: ' + err);
    }
}

async function triggerHotReload() {
    try {
        const res = await fetch(`${API_BASE}/api/v1/system/hot_reload`, { method: 'POST' });
        const data = await res.json();
        alert(data.message || '라이브 코드 패치 완료!');
    } catch (err) {
        alert('핫 리로드 실패: ' + err);
    }
}

async function emergencyStopAll() {
    if (!confirm('⚠️ 경고: 60대 전체 구동 세션을 즉시 강제 중지하고 중앙 API에 FAIL을 리포트하시겠습니까?')) return;

    try {
        const res = await fetch(`${API_BASE}/api/v1/system/emergency_stop`, { method: 'POST' });
        const data = await res.json();
        alert(`전체 강제 중지 완료! 총 ${data.stopped_devices_count}대 단말기가 안전 종료되었습니다.`);
        fetchDevices();
    } catch (err) {
        alert('비상 중지 실패: ' + err);
    }
}
