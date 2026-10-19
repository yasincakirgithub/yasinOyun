(function () {
    const section = document.querySelector('.comments[data-game]');
    if (!section) return;

    const game = section.dataset.game;
    const list = section.querySelector('#comments-list');
    const form = section.querySelector('#comment-form');
    const nameInput = section.querySelector('#comment-name');
    const bodyInput = section.querySelector('#comment-body');
    const status = section.querySelector('#comment-status');
    const submitBtn = form.querySelector('.comment-submit');
    const apiUrl = '/api/comments/' + encodeURIComponent(game) + '/';
    const nameKey = 'oyunlar:commentName';

    const savedName = localStorage.getItem(nameKey);
    if (savedName && nameInput) nameInput.value = savedName;

    function escapeHtml(value) {
        return String(value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function createItem(comment) {
        const item = document.createElement('article');
        item.className = 'comment-item';

        const head = document.createElement('div');
        head.className = 'comment-head';

        const author = document.createElement('span');
        author.className = 'comment-author';
        author.textContent = comment.author;

        const time = document.createElement('time');
        time.className = 'comment-time';
        time.textContent = comment.created_at;

        const body = document.createElement('p');
        body.className = 'comment-text';
        body.textContent = comment.body;

        head.appendChild(author);
        head.appendChild(time);
        item.appendChild(head);
        item.appendChild(body);
        return item;
    }

    function renderList(comments) {
        list.innerHTML = '';
        if (!comments.length) {
            const empty = document.createElement('p');
            empty.className = 'comments-empty';
            empty.textContent = 'Henüz yorum yok. İlk yorumu sen yap!';
            list.appendChild(empty);
            return;
        }
        comments.forEach((comment) => list.appendChild(createItem(comment)));
    }

    function loadComments() {
        fetch(apiUrl)
            .then((response) => response.json())
            .then((data) => {
                if (!data.success) throw new Error(data.error || 'Yüklenemedi');
                renderList(data.comments);
            })
            .catch(() => {
                list.innerHTML = '';
                const error = document.createElement('p');
                error.className = 'comments-empty';
                error.textContent = 'Yorumlar yüklenemedi.';
                list.appendChild(error);
            });
    }

    form.addEventListener('submit', (event) => {
        event.preventDefault();
        const body = bodyInput.value.trim();
        if (!body) {
            bodyInput.focus();
            return;
        }

        const name = (nameInput && nameInput.value.trim()) || '';
        if (name) localStorage.setItem(nameKey, name);

        submitBtn.disabled = true;
        status.textContent = 'Gönderiliyor...';
        status.className = 'comment-status';

        fetch(apiUrl, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, body }),
        })
            .then((response) => response.json())
            .then((data) => {
                if (!data.success) throw new Error(data.error || 'Gönderilemedi.');
                const empty = list.querySelector('.comments-empty');
                if (empty) empty.remove();
                list.insertBefore(createItem(data.comment), list.firstChild);
                bodyInput.value = '';
                status.textContent = 'Yorumun eklendi.';
                status.classList.add('success');
                window.setTimeout(() => {
                    status.textContent = '';
                    status.classList.remove('success');
                }, 2500);
            })
            .catch((error) => {
                status.textContent = error.message || 'Gönderilemedi.';
                status.classList.add('error');
            })
            .finally(() => {
                submitBtn.disabled = false;
            });
    });

    loadComments();
})();
