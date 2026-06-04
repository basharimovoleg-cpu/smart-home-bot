/**
 * Mini App v3.0: Домашний Помощник
 * SPA с Bottom Navigation — Главная, Рецепты, История.
 */

const tg = window.Telegram.WebApp;
tg.ready();
tg.expand();

const initData = tg.initData;

// ═══════════════════════════════════════════════════════════
// API-клиент
// ═══════════════════════════════════════════════════════════

const API = {
    async request(endpoint, options = {}) {
        const resp = await fetch(endpoint, {
            ...options,
            headers: {
                'X-Telegram-Init-Data': initData,
                ...(options.headers || {}),
            },
        });
        // для FormData не ставим Content-Type, браузер сам
        if (!options.body || !(options.body instanceof FormData)) {
            resp.headers; // no-op
        }
        const text = await resp.text();
        if (!resp.ok) {
            let msg = `Ошибка ${resp.status}`;
            try { const err = JSON.parse(text); msg = err.detail || msg; } catch {}
            throw new Error(msg);
        }
        return text ? JSON.parse(text) : {};
    },

    // Свет
    toggleLight(mode) {
        return this.request('/api/light/toggle', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ mode }),
        });
    },
    getLightStatus() { return this.request('/api/light/status'); },

    // ПК (сон)
    pcSleep() {
        return this.request('/api/pc/sleep', { method: 'POST' });
    },
    pcWake() {
        return this.request('/api/pc/wake', { method: 'POST' });
    },

    // Кино
    searchMovies(query, quality) {
        return this.request(`/api/movies/search?q=${encodeURIComponent(query)}&quality=${encodeURIComponent(quality)}`);
    },
    addMovieDownload(torrent_id, title, quality, size_text, category) {
        return this.request('/api/movies/download', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ torrent_id, title, quality, size_text, category }),
        });
    },
    getMovieDownloads() {
        return this.request('/api/movies/downloads');
    },
    deleteMovieDownload(downloadId) {
        return this.request(`/api/movies/downloads/${downloadId}`, { method: 'DELETE' });
    },

    // Задачи
    getTasks()         { return this.request('/api/tasks'); },
    createTask(title, task_date) {
        return this.request('/api/tasks', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title, task_date }),
        });
    },
    completeTask(taskId) {
        return this.request(`/api/tasks/${taskId}/complete`, { method: 'POST' });
    },
    deleteTask(taskId) {
        return this.request(`/api/tasks/${taskId}`, { method: 'DELETE' });
    },
    updateTask(taskId, data) {
        return this.request(`/api/tasks/${taskId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
    },
    getHistory() { return this.request('/api/tasks/history'); },
    returnTask(historyId) {
        return this.request(`/api/tasks/history/${historyId}/return`, { method: 'POST' });
    },

    // Категории
    getCategories() { return this.request('/api/categories'); },
    createCategory(name) {
        return this.request('/api/categories', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name }),
        });
    },
    deleteCategory(categoryId) {
        return this.request(`/api/categories/${categoryId}`, { method: 'DELETE' });
    },

    // Рецепты
    getRecipes(categoryId) {
        const q = categoryId ? `?category_id=${categoryId}` : '';
        return this.request(`/api/recipes${q}`);
    },
    createRecipe(formData) {
        return this.request('/api/recipes', {
            method: 'POST',
            body: formData,  // FormData — браузер сам проставит multipart/form-data
        });
    },
    updateRecipe(recipeId, formData) {
        return this.request(`/api/recipes/${recipeId}`, {
            method: 'PUT',
            body: formData,
        });
    },
    deleteRecipe(recipeId) {
        return this.request(`/api/recipes/${recipeId}`, { method: 'DELETE' });
    },
};

// ═══════════════════════════════════════════════════════════
// Toast
// ═══════════════════════════════════════════════════════════

function showToast(message, type = 'error', duration = 3000) {
    const toast = document.getElementById('toast');
    toast.textContent = message;
    toast.className = 'toast';  // сброс: убираем hidden и success
    if (type === 'success') toast.classList.add('success');
    clearTimeout(toast._timeout);
    toast._timeout = setTimeout(() => toast.classList.add('hidden'), duration);
}

// ═══════════════════════════════════════════════════════════
// SPA: навигация между вкладками
// ═══════════════════════════════════════════════════════════

function switchTab(tabName) {
    document.querySelectorAll('.tab-page').forEach(p => p.classList.remove('active'));
    document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));

    document.getElementById(`tab-${tabName}`).classList.add('active');
    document.querySelector(`[data-tab="${tabName}"]`).classList.add('active');

    if (tabName === 'recipes') loadRecipePage();
    if (tabName === 'history') loadHistory();
    if (tabName === 'movies') { loadMovieDownloads(); movieDownloadsInterval = setInterval(loadMovieDownloads, 5000); }
    else { clearInterval(movieDownloadsInterval); }
}

document.querySelectorAll('.nav-btn').forEach(btn => {
    btn.addEventListener('click', () => switchTab(btn.dataset.tab));
});

// ═══════════════════════════════════════════════════════════
// Главная: Свет
// ═══════════════════════════════════════════════════════════

async function loadLightStatus() {
    const el = document.getElementById('light-status');
    try {
        const data = await API.getLightStatus();
        const obodki = data.obodki ? '<span class="on">ВКЛ</span>' : '<span class="off">ВЫКЛ</span>';
        const main = data.main_light ? '<span class="on">ВКЛ</span>' : '<span class="off">ВЫКЛ</span>';
        el.innerHTML = `Ободки: ${obodki}<br>Основной свет: ${main}`;
    } catch (e) {
        el.textContent = 'Недоступно';
    }
}

async function handleLightToggle(mode, btn) {
    btn.disabled = true;
    const original = btn.textContent;
    btn.textContent = '⏳...';
    try {
        const data = await API.toggleLight(mode);
        const ob = data.obodki ? '<span class="on">ВКЛ</span>' : '<span class="off">ВЫКЛ</span>';
        const ml = data.main_light ? '<span class="on">ВКЛ</span>' : '<span class="off">ВЫКЛ</span>';
        document.getElementById('light-status').innerHTML = `Ободки: ${ob}<br>Основной свет: ${ml}`;
    } catch (e) {
        showToast(e.message || 'Ошибка');
    } finally {
        btn.disabled = false;
        btn.textContent = original;
    }
}

// ═══════════════════════════════════════════════════════════
// Главная: Усыпление ПК
// ═══════════════════════════════════════════════════════════

async function handlePcSleep() {
    const btn = document.getElementById('pc-sleep-btn');
    const status = document.getElementById('pc-status');
    const original = btn.textContent;

    btn.disabled = true;
    btn.textContent = '⏳ Отправка...';
    status.textContent = '';

    try {
        const data = await API.pcSleep();
        showToast(data.message || 'ПК уходит в сон 💤', 'success', 4000);
        status.textContent = data.message || 'ПК уходит в сон 💤';
        status.style.color = '#2e7d32';
    } catch (e) {
        const msg = (e.message || '').toLowerCase();
        if (
            msg.includes('failed to fetch') ||
            msg.includes('networkerror') ||
            msg.includes('ошибка 502') ||
            msg.includes('ошибка 504')
        ) {
            showToast('ПК успешно уснул 💤', 'success', 4000);
            status.textContent = 'ПК успешно уснул 💤';
            status.style.color = '#2e7d32';
        } else {
            showToast(e.message || 'Ошибка подключения к ПК');
            status.textContent = '❌ ' + (e.message || 'Ошибка');
            status.style.color = '#c62828';
        }
    } finally {
        btn.disabled = false;
        btn.textContent = original;
    }
}

async function handlePcWake() {
    const btn = document.getElementById('pc-wake-btn');
    const status = document.getElementById('pc-status');
    const original = btn.textContent;

    btn.disabled = true;
    btn.textContent = '⏳ Отправка...';
    status.textContent = '';

    try {
        const data = await API.pcWake();
        showToast(data.message || 'ПК просыпается ⚡', 'success', 4000);
        status.textContent = data.message || 'ПК просыпается ⚡';
        status.style.color = '#2e7d32';
    } catch (e) {
        showToast(e.message || 'Ошибка отправки Wake-on-LAN');
        status.textContent = '❌ ' + (e.message || 'Ошибка');
        status.style.color = '#c62828';
    } finally {
        btn.disabled = false;
        btn.textContent = original;
    }
}

// ═══════════════════════════════════════════════════════════
// Главная: Задачи
// ═══════════════════════════════════════════════════════════

async function loadTasks() {
    const el = document.getElementById('tasks-list');
    try {
        const data = await API.getTasks();
        const tasks = data.tasks || [];
        if (tasks.length === 0) {
            el.innerHTML = '<div class="empty-state">Нет активных задач 🎉</div>';
            return;
        }
        el.innerHTML = tasks.map(t => `
            <div class="task-item" id="task-${t.id}">
                <div class="task-info">
                    <div class="task-title">${escapeHtml(t.title)}</div>
                    <div class="task-date">📅 ${formatDate(t.task_date)}</div>
                </div>
                <button class="task-edit-btn" onclick="editTask(${t.id})" title="Редактировать">✏️</button>
                <button class="task-done-btn" onclick="completeTask(${t.id})" title="Выполнено">✓</button>
                <button class="task-delete-btn" onclick="deleteTaskById(${t.id})" title="Удалить">✕</button>
            </div>
        `).join('');
    } catch (e) {
        el.innerHTML = '<div class="loading">Ошибка загрузки</div>';
    }
}

async function completeTask(taskId) {
    try {
        await API.completeTask(taskId);
        const item = document.getElementById(`task-${taskId}`);
        if (item) { item.style.opacity = '0.5'; setTimeout(() => { item.remove(); checkEmptyTasks(); }, 300); }
    } catch (e) { showToast('Ошибка'); }
}

async function deleteTaskById(taskId) {
    try {
        await API.deleteTask(taskId);
        const item = document.getElementById(`task-${taskId}`);
        if (item) { item.style.opacity = '0.5'; setTimeout(() => { item.remove(); checkEmptyTasks(); }, 300); }
    } catch (e) { showToast('Ошибка'); }
}

let editingTaskId = null;

async function editTask(taskId) {
    const item = document.getElementById(`task-${taskId}`);
    if (!item) return;
    const titleEl = item.querySelector('.task-title');
    const dateEl = item.querySelector('.task-date');
    const displayDate = dateEl ? dateEl.textContent.replace('📅 ', '') : '';
    const parts = displayDate.split('.');
    const isoDate = parts.length === 3 ? `${parts[2]}-${parts[1]}-${parts[0]}` : '';

    editingTaskId = taskId;
    document.getElementById('edit-task-title').value = titleEl ? titleEl.textContent : '';
    document.getElementById('edit-task-date').value = isoDate;
    document.getElementById('edit-task-error').classList.add('hidden');
    openModal('task-edit-modal');
}

function checkEmptyTasks() {
    const list = document.getElementById('tasks-list');
    if (!list.querySelector('.task-item')) list.innerHTML = '<div class="empty-state">Нет активных задач 🎉</div>';
}

// ═══════════════════════════════════════════════════════════
// История
// ═══════════════════════════════════════════════════════════

async function loadHistory() {
    const el = document.getElementById('history-list');
    const btn = document.getElementById('load-history-btn');
    btn.disabled = true; btn.textContent = '⏳ Загрузка...';
    try {
        const data = await API.getHistory();
        const history = data.history || [];
        if (history.length === 0) { el.innerHTML = '<div class="empty-state">История пуста</div>'; return; }

        el.innerHTML = history.map((g, gi) => `
            <div class="history-group" data-group="${gi}">
                <div class="history-date">
                    <span class="history-arrow">▶</span>
                    📆 ${escapeHtml(g.date)}
                    <span class="history-count">(${g.items.length})</span>
                </div>
                <div class="history-items">
                    ${g.items.map(i => `
                        <div class="history-item" id="hist-${i.id}">
                            <span class="history-title">${escapeHtml(i.title)}</span>
                            <span class="history-by">👤 ${escapeHtml(i.completed_by_name)}</span>
                            <button class="task-return-btn" onclick="returnTask(${i.id})" title="Вернуть в задачи">↩</button>
                        </div>
                    `).join('')}
                </div>
            </div>
        `).join('');

        // Аккордеон: клик по дате → раскрыть/свернуть
        el.querySelectorAll('.history-date').forEach(dateEl => {
            dateEl.addEventListener('click', function() {
                const group = this.parentElement;
                const items = group.querySelector('.history-items');
                const isOpen = items.classList.contains('open');

                // Закрыть все остальные (аккордеон)
                el.querySelectorAll('.history-group.open').forEach(g => g.classList.remove('open'));
                el.querySelectorAll('.history-items.open').forEach(o => o.classList.remove('open'));

                // Переключить текущий
                if (!isOpen) {
                    group.classList.add('open');
                    items.classList.add('open');
                }
            });
        });
    } catch (e) {
        el.innerHTML = '<div class="loading">Ошибка загрузки</div>';
    } finally {
        btn.disabled = false; btn.textContent = 'Загрузить историю';
    }
}

async function returnTask(historyId) {
    const item = document.getElementById(`hist-${historyId}`);
    try {
        await API.returnTask(historyId);
        if (item) {
            item.style.opacity = '0.5';
            setTimeout(() => {
                item.remove();
                const group = item.closest('.history-group');
                if (group) {
                    const items = group.querySelectorAll('.history-item');
                    if (items.length === 0) group.remove();
                }
            }, 300);
        }
        await loadTasks();
        showToast('Задача возвращена', 'success');
    } catch (e) {
        showToast('Ошибка возврата задачи');
    }
}

// ═══════════════════════════════════════════════════════════
// Кино
// ═══════════════════════════════════════════════════════════

async function searchMovies() {
    const input = document.getElementById('movie-search-input');
    const quality = document.getElementById('movie-quality-select').value;
    const status = document.getElementById('movie-search-status');
    const results = document.getElementById('movie-results');
    const query = input.value.trim();

    if (query.length < 2) {
        showToast('Введите минимум 2 символа');
        return;
    }

    status.textContent = '⏳ Поиск...';
    results.innerHTML = '';

    try {
        const data = await API.searchMovies(query, quality);
        const items = data.results || [];
        if (items.length === 0) {
            status.textContent = 'Ничего не найдено';
            results.innerHTML = '<div class="empty-state">Ничего не найдено 😕</div>';
            return;
        }
        status.textContent = `Найдено: ${items.length}`;
        
        status.textContent = `Найдено: ${items.length}`;
        results.innerHTML = items.map(r => `
            <div style="display:block;background:var(--tg-theme-secondary-bg-color, #f0f0f0);padding:10px 12px;margin:6px 0;border-radius:10px;border-left:4px solid var(--tg-theme-button-color, #3390ec);">
                <div style="color:var(--tg-theme-text-color, #000);font-size:13px;font-weight:600;line-height:1.3;margin-bottom:4px;">${escapeHtml(r.title)}</div>
                <div style="display:flex;flex-wrap:wrap;align-items:center;gap:6px;font-size:11px;color:var(--tg-theme-hint-color, #666);margin-bottom:4px;">
                    <span style="display:inline-block;padding:1px 5px;border-radius:3px;font-weight:700;font-size:10px;color:#fff;background:${r.quality.includes('4K') ? '#e91e63' : r.quality.includes('1080p') ? '#2196f3' : '#ff9800'};">${r.quality}</span>
                    ${r.year ? `<span>📅 ${r.year}</span>` : ''}
                    <span>📦 ${escapeHtml(r.size_text)}</span>
                    <span>🔽 ${r.seeds}</span>
                    <span>${r.category === 'series' ? '📺 Сериал' : '🎬 Фильм'}</span>
                </div>
                <button class="btn btn-primary btn-sm" onclick="startDownload('${escapeAttr(r.torrent_id)}', '${escapeAttr(r.title)}', '${escapeAttr(r.quality)}', '${escapeAttr(r.size_text)}', '${escapeAttr(r.category)}')">📥 Скачать</button>
            </div>
        `).join('');
    } catch (e) {
        status.textContent = 'Ошибка поиска';
        showToast(e.message || 'Ошибка поиска');
    }
}

async function startDownload(torrentId, title, quality, sizeText, category) {
    try {
        const data = await API.addMovieDownload(torrentId, title, quality, sizeText, category);
        showToast(data.message || 'Загрузка начата', 'success', 3000);
        await loadMovieDownloads();
    } catch (e) {
        showToast(e.message || 'Ошибка загрузки');
    }
}

let movieDownloadsInterval = null;

async function loadMovieDownloads() {
    const el = document.getElementById('movie-downloads');
    try {
        const data = await API.getMovieDownloads();
        const items = data.downloads || [];
        if (items.length === 0) {
            el.innerHTML += '<div class="empty-state">Нет активных загрузок</div>';
            return;
        }
        el.innerHTML = items.map(d => `
            <div style="padding:10px 12px;margin:6px 0;background:#1e1e1e;border-radius:10px;">
                <div style="color:#fff;font-size:13px;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;margin-bottom:4px;">${escapeHtml(d.title)}</div>
                <div style="display:flex;flex-wrap:wrap;gap:6px;font-size:11px;color:#aaa;margin-bottom:6px;">
                    <span style="display:inline-block;padding:1px 5px;border-radius:3px;font-weight:700;font-size:10px;color:#fff;background:${d.quality.includes('4K') ? '#e91e63' : d.quality.includes('1080p') ? '#2196f3' : '#ff9800'};">${d.quality}</span>
                    <span>${d.category === 'series' ? '📺 Сериал' : '🎬 Фильм'}</span>
                    <span>${escapeHtml(d.size_text)}</span>
                </div>
                <div style="width:100%;height:6px;background:#444;border-radius:3px;overflow:hidden;margin-bottom:2px;">
                    <div style="height:100%;border-radius:3px;width:${d.progress}%;background:${d.state === 'completed' ? '#4caf50' : '#2196f3'};"></div>
                </div>
                <div style="display:flex;justify-content:space-between;align-items:center;">
                    <span style="font-size:11px;color:#aaa;">${stateLabel(d.state)}</span>
                    <span style="font-size:12px;font-weight:600;color:#2196f3;">${d.progress}%</span>
                </div>
                <button class="btn btn-sm" style="margin-top:6px;background:transparent;border:1px solid #f44336;color:#f44336;border-radius:6px;padding:4px 12px;font-size:12px;" onclick="deleteDownload(${d.id})">🗑 Удалить</button>
            </div>
        `).join('');
    } catch (e) {
        el.innerHTML = '<div class="loading">Ошибка загрузки</div>';
    }
}

function stateLabel(state) {
    if (state === 'completed') return '✅ Готово';
    if (state === 'downloading') return '⏳ Качается';
    if (state === 'pausedDL') return '⏸ Пауза';
    return '📦 ' + state;
}

async function deleteDownload(downloadId) {
    try {
        await API.deleteMovieDownload(downloadId);
        await loadMovieDownloads();
        showToast('Удалено', 'success');
    } catch (e) {
        showToast('Ошибка удаления');
    }
}


// ═══════════════════════════════════════════════════════════
// Рецепты
// ═══════════════════════════════════════════════════════════

let activeCategoryId = null;
let allCategories = [];

async function loadRecipePage() {
    await loadCategories();
    await loadRecipes();
}

async function loadCategories() {
    try {
        allCategories = await API.getCategories();
        renderChips();
        // Обновляем <select> в форме рецепта
        const sel = document.getElementById('recipe-category');
        sel.innerHTML = allCategories.map(c => `<option value="${c.id}">${escapeHtml(c.name)}</option>`).join('');
    } catch (e) {
        showToast('Ошибка загрузки категорий');
    }
}

function renderChips() {
    const container = document.getElementById('chips-container');
    container.innerHTML = '<button class="chip active" data-category-id="">Все</button>' +
        allCategories.map(c =>
            `<button class="chip" data-category-id="${c.id}">${escapeHtml(c.name)}</button>`
        ).join('');

    container.querySelectorAll('.chip').forEach(chip => {
        chip.addEventListener('click', () => {
            container.querySelectorAll('.chip').forEach(c => c.classList.remove('active'));
            chip.classList.add('active');
            activeCategoryId = chip.dataset.categoryId || null;
            updateDeleteCategoryButton();
            loadRecipes();
        });
    });
}

let currentRecipe = null;  // рецепт, открытый в detail-модалке

async function loadRecipes() {
    const grid = document.getElementById('recipe-grid');
    try {
        const recipes = await API.getRecipes(activeCategoryId || undefined);
        if (recipes.length === 0) {
            grid.innerHTML = '<div class="empty-state">Нет рецептов</div>';
            return;
        }
        grid.innerHTML = '';
        recipes.forEach(r => {
            const card = document.createElement('div');
            card.className = 'recipe-card';

            if (r.image_url) {
                const img = document.createElement('img');
                img.src = r.image_url;
                img.alt = r.title;
                img.className = 'recipe-img';
                card.appendChild(img);
            } else {
                const ph = document.createElement('div');
                ph.className = 'recipe-img-placeholder';
                ph.textContent = '🍽';
                card.appendChild(ph);
            }

            const titleEl = document.createElement('div');
            titleEl.className = 'recipe-card-title';
            titleEl.textContent = r.title;
            card.appendChild(titleEl);

            card.onclick = () => showRecipeDetail(r);
            grid.appendChild(card);
        });
    } catch (e) {
        grid.innerHTML = '<div class="loading">Ошибка загрузки</div>';
    }
}

function showRecipeDetail(recipe) {
    currentRecipe = recipe;
    document.getElementById('detail-title').textContent = recipe.title;
    document.getElementById('detail-ingredients').textContent = recipe.ingredients;
    document.getElementById('detail-steps').textContent = recipe.steps;
    const img = document.getElementById('detail-image');
    if (recipe.image_url && recipe.image_url !== 'null' && recipe.image_url !== '') {
        img.src = recipe.image_url;
        img.style.display = 'block';
    } else {
        img.style.display = 'none';
    }
    openModal('recipe-detail-modal');
}

// ═══════════════════════════════════════════════════════════
// Модальные окна
// ═══════════════════════════════════════════════════════════

function openModal(id) { document.getElementById(id).classList.remove('hidden'); }
function closeModal(id) { document.getElementById(id).classList.add('hidden'); }
function closeAllModals() {
    document.querySelectorAll('.modal').forEach(m => m.classList.add('hidden'));
}

document.querySelectorAll('.modal-overlay').forEach(ov => {
    ov.addEventListener('click', () => closeAllModals());
});
document.querySelectorAll('.close-modal-btn').forEach(btn => {
    btn.addEventListener('click', () => closeAllModals());
});

// Задача
document.getElementById('add-task-btn').addEventListener('click', () => {
    document.getElementById('task-title').value = '';
    document.getElementById('task-date').value = new Date().toISOString().split('T')[0];
    document.getElementById('modal-error').classList.add('hidden');
    openModal('task-modal');
});
document.getElementById('save-task').addEventListener('click', async () => {
    const title = document.getElementById('task-title').value.trim();
    const dt = document.getElementById('task-date').value;
    if (!title) { document.getElementById('modal-error').classList.remove('hidden'); document.getElementById('modal-error').textContent = 'Введите название'; return; }
    if (!dt) { document.getElementById('modal-error').classList.remove('hidden'); document.getElementById('modal-error').textContent = 'Выберите дату'; return; }
    try {
        await API.createTask(title, dt);
        closeModal('task-modal');
        await loadTasks();
    } catch (e) { showToast(e.message); }
});

// Редактирование задачи
document.getElementById('save-edit-task').addEventListener('click', async () => {
    const title = document.getElementById('edit-task-title').value.trim();
    const dt = document.getElementById('edit-task-date').value;
    if (!title) { document.getElementById('edit-task-error').classList.remove('hidden'); document.getElementById('edit-task-error').textContent = 'Введите название'; return; }
    if (!dt) { document.getElementById('edit-task-error').classList.remove('hidden'); document.getElementById('edit-task-error').textContent = 'Выберите дату'; return; }
    if (!editingTaskId) return;
    try {
        await API.updateTask(editingTaskId, { title, task_date: dt });
        closeModal('task-edit-modal');
        editingTaskId = null;
        await loadTasks();
    } catch (e) { showToast(e.message); }
});

// Категория
document.getElementById('add-category-btn').addEventListener('click', () => {
    document.getElementById('category-name').value = '';
    document.getElementById('cat-error').classList.add('hidden');
    openModal('category-modal');
});
document.getElementById('save-category').addEventListener('click', async () => {
    const name = document.getElementById('category-name').value.trim();
    if (!name) { document.getElementById('cat-error').classList.remove('hidden'); document.getElementById('cat-error').textContent = 'Введите название'; return; }
    try {
        await API.createCategory(name);
        closeModal('category-modal');
        await loadCategories();
    } catch (e) { showToast(e.message); }
});

// Кнопка «Удалить категорию» — показывается только при выборе пользовательской категории
function updateDeleteCategoryButton() {
    const btn = document.getElementById('delete-category-btn');
    if (activeCategoryId) {
        btn.classList.remove('hidden');
    } else {
        btn.classList.add('hidden');
    }
}

document.getElementById('delete-category-btn').addEventListener('click', async () => {
    if (!activeCategoryId) return;
    const cat = allCategories.find(c => c.id === parseInt(activeCategoryId));
    const catName = cat ? cat.name : 'эту категорию';
    if (!confirm(`Удалить категорию «${catName}»?\nРецепты из этой категории не будут удалены.`)) return;
    try {
        await API.deleteCategory(activeCategoryId);
        activeCategoryId = null;
        await loadCategories();
        // Переключаем чипс на «Все»
        const container = document.getElementById('chips-container');
        container.querySelectorAll('.chip').forEach(c => c.classList.remove('active'));
        const allChip = container.querySelector('[data-category-id=""]');
        if (allChip) allChip.classList.add('active');
        updateDeleteCategoryButton();
        await loadRecipes();
        showToast('Категория удалена');
    } catch (e) { showToast(e.message); }
});

// Рецепт
document.getElementById('add-recipe-btn').addEventListener('click', async () => {
    document.getElementById('recipe-title').value = '';
    document.getElementById('recipe-ingredients').value = '';
    document.getElementById('recipe-steps').value = '';
    document.getElementById('recipe-image').value = '';
    document.getElementById('recipe-error').classList.add('hidden');
    // Обновить select категорий
    try {
        const cats = await API.getCategories();
        document.getElementById('recipe-category').innerHTML =
            cats.map(c => `<option value="${c.id}">${escapeHtml(c.name)}</option>`).join('');
    } catch {}
    openModal('recipe-modal');
});
document.getElementById('save-recipe').addEventListener('click', async () => {
    const title = document.getElementById('recipe-title').value.trim();
    const catId = document.getElementById('recipe-category').value;
    const ingredients = document.getElementById('recipe-ingredients').value.trim();
    const steps = document.getElementById('recipe-steps').value.trim();
    const imageFile = document.getElementById('recipe-image').files[0];

    if (!title) { document.getElementById('recipe-error').classList.remove('hidden'); document.getElementById('recipe-error').textContent = 'Введите название'; return; }
    if (!catId) { document.getElementById('recipe-error').classList.remove('hidden'); document.getElementById('recipe-error').textContent = 'Создайте категорию'; return; }

    const fd = new FormData();
    fd.append('title', title);
    fd.append('category_id', catId);
    fd.append('ingredients', ingredients);
    fd.append('steps', steps);
    if (imageFile) fd.append('image', imageFile);

    try {
        await API.createRecipe(fd);
        closeModal('recipe-modal');
        await loadRecipes();
        showToast('Рецепт создан', 'success');
    } catch (e) { showToast(e.message); }
});

// ── Редактирование / Удаление рецепта ──

// Кнопка «Редактировать» в модалке деталей
document.getElementById('edit-recipe-btn').addEventListener('click', () => {
    if (!currentRecipe) return;
    closeModal('recipe-detail-modal');
    openEditRecipeModal(currentRecipe);
});

function openEditRecipeModal(recipe) {
    document.getElementById('edit-recipe-title').value = recipe.title;
    document.getElementById('edit-recipe-ingredients').value = recipe.ingredients;
    document.getElementById('edit-recipe-steps').value = recipe.steps;
    document.getElementById('edit-recipe-image').value = '';
    document.getElementById('edit-recipe-error').classList.add('hidden');

    const sel = document.getElementById('edit-recipe-category');
    sel.innerHTML = allCategories.map(c =>
        `<option value="${c.id}" ${c.id === recipe.category_id ? 'selected' : ''}>${escapeHtml(c.name)}</option>`
    ).join('');

    openModal('recipe-edit-modal');
}

// Кнопка «Сохранить» в модалке редактирования
document.getElementById('save-edit-recipe').addEventListener('click', async () => {
    if (!currentRecipe) return;
    const title = document.getElementById('edit-recipe-title').value.trim();
    const catId = document.getElementById('edit-recipe-category').value;
    const ingredients = document.getElementById('edit-recipe-ingredients').value.trim();
    const steps = document.getElementById('edit-recipe-steps').value.trim();
    const imageFile = document.getElementById('edit-recipe-image').files[0];

    if (!title) {
        document.getElementById('edit-recipe-error').classList.remove('hidden');
        document.getElementById('edit-recipe-error').textContent = 'Введите название';
        return;
    }

    const fd = new FormData();
    fd.append('title', title);
    fd.append('category_id', catId);
    fd.append('ingredients', ingredients);
    fd.append('steps', steps);
    if (imageFile) fd.append('image', imageFile);

    try {
        await API.updateRecipe(currentRecipe.id, fd);
        closeAllModals();
        await loadRecipes();
        showToast('Рецепт обновлён', 'success');
    } catch (e) {
        document.getElementById('edit-recipe-error').classList.remove('hidden');
        document.getElementById('edit-recipe-error').textContent = e.message;
    }
});

// Кнопка «Удалить» в модалке редактирования
document.getElementById('delete-recipe-btn').addEventListener('click', async () => {
    if (!currentRecipe) return;
    if (!confirm(`Удалить рецепт «${currentRecipe.title}»?`)) return;
    try {
        await API.deleteRecipe(currentRecipe.id);
        closeAllModals();
        await loadRecipes();
        showToast('Рецепт удалён');
    } catch (e) { showToast(e.message); }
});

// ═══════════════════════════════════════════════════════════
// Утилиты
// ═══════════════════════════════════════════════════════════

function escapeHtml(s) {
    const d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
}

function escapeAttr(s) {
    return (s || '').replace(/&/g, '&amp;').replace(/\\/g, '\\\\').replace(/'/g, "\\'").replace(/"/g, '&quot;').replace(/\n/g, '\\n');
}

function formatDate(dateStr) {
    const parts = dateStr.split('-');
    return parts.length === 3 ? `${parts[2]}.${parts[1]}.${parts[0]}` : dateStr;
}

// ═══════════════════════════════════════════════════════════
// Настройки
// ═══════════════════════════════════════════════════════════

async function loadSettings() {
    try {
        const data = await API.request('/api/settings');
        if (data.rutracker_user) document.getElementById('setting-rutracker-user').value = data.rutracker_user;
        if (data.rutracker_pass) document.getElementById('setting-rutracker-pass').value = data.rutracker_pass;
    } catch (e) {
        // silently ignore
    }
}

async function saveSettings() {
    const statusEl = document.getElementById('settings-status');
    const btn = document.getElementById('save-settings-btn');
    const user = document.getElementById('setting-rutracker-user').value.trim();
    const pass = document.getElementById('setting-rutracker-pass').value.trim();

    btn.disabled = true;
    btn.textContent = '⏳ Сохраняю...';
    statusEl.textContent = '';
    statusEl.style.color = '#888';

    try {
        if (user) await API.request('/api/settings', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({key: 'rutracker_user', value: user}),
        });
        if (pass) await API.request('/api/settings', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({key: 'rutracker_pass', value: pass}),
        });

        statusEl.textContent = '✅ Настройки сохранены! Поиск фильмов должен заработать.';
        statusEl.style.color = '#4caf50';
    } catch (e) {
        statusEl.textContent = '❌ Ошибка: ' + (e.message || 'не удалось сохранить');
        statusEl.style.color = '#f44336';
    } finally {
        btn.disabled = false;
        btn.textContent = '💾 Сохранить';
    }
}

// ═══════════════════════════════════════════════════════════
// Инициализация
// ═══════════════════════════════════════════════════════════

document.addEventListener('DOMContentLoaded', () => {
    loadLightStatus();
    loadTasks();

    // Свет
    document.getElementById('light-toggle-all').addEventListener('click', function() { handleLightToggle('all', this); });
    document.getElementById('light-toggle-main').addEventListener('click', function() { handleLightToggle('main', this); });
    document.getElementById('light-toggle-rims').addEventListener('click', function() { handleLightToggle('rims', this); });

    // Усыпление ПК
    document.getElementById('pc-sleep-btn').addEventListener('click', handlePcSleep);
    document.getElementById('pc-wake-btn').addEventListener('click', handlePcWake);

    // Кино
    document.getElementById('movie-search-btn').addEventListener('click', searchMovies);
    document.getElementById('movie-search-input').addEventListener('keydown', (e) => {
        if (e.key === 'Enter') { e.preventDefault(); searchMovies(); }
    });
    document.getElementById('refresh-downloads-btn').addEventListener('click', loadMovieDownloads);

    // Esc закрывает модалки
    document.addEventListener('keydown', e => { if (e.key === 'Escape') closeAllModals(); });

    // Настройки
    loadSettings();
    document.getElementById('save-settings-btn').addEventListener('click', saveSettings);
});
