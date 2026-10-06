// Pasted, dropped or picked images wait in a JS list, shown as thumbnails, and only reach the
// form's file input on submit: a file input cannot be appended to, only replaced.
const MESSAGING_IMAGE_TYPES = ['image/png', 'image/jpeg', 'image/webp', 'image/gif'];
// Same cap as the server: nginx refuses a request body over 10m.
const MESSAGING_MAX_IMAGES_SIZE = 9 * 1024 * 1024;
const MESSAGING_MAX_IMAGES = 10;

document.querySelectorAll('form[data-messaging-images]').forEach((form) => {
    const textarea = form.querySelector('textarea[name="text"]');
    const fileInput = form.querySelector('.messaging-file-input');
    const thumbnails = form.querySelector('.messaging-thumbnails');
    let images = [];

    function addImages(files) {
        for (const file of files) {
            if (!MESSAGING_IMAGE_TYPES.includes(file.type)) {
                alert("Format d'image non supporté (PNG, JPEG, WEBP ou GIF).");
                continue;
            }
            if (images.length >= MESSAGING_MAX_IMAGES) {
                alert(`${MESSAGING_MAX_IMAGES} images maximum par message.`);
                break;
            }
            const totalSize = images.reduce((total, image) => total + image.size, 0);
            if (totalSize + file.size > MESSAGING_MAX_IMAGES_SIZE) {
                alert("Les images d'un message ne doivent pas dépasser 9 Mo au total.");
                break;
            }
            images.push(file);
        }
        render();
    }

    function render() {
        thumbnails.querySelectorAll('img').forEach((img) => URL.revokeObjectURL(img.src));
        thumbnails.replaceChildren(...images.map((file, index) => {
            const item = document.createElement('div');
            item.className = 'messaging-thumbnail';
            const img = document.createElement('img');
            img.src = URL.createObjectURL(file);
            img.alt = file.name;
            const remove = document.createElement('button');
            remove.type = 'button';
            remove.className = 'messaging-thumbnail-remove';
            remove.title = 'Retirer';
            remove.innerHTML = '&times;';
            remove.addEventListener('click', () => {
                images.splice(index, 1);
                render();
            });
            item.append(img, remove);
            return item;
        }));
    }

    textarea.addEventListener('paste', (event) => {
        const files = Array.from(event.clipboardData?.files || [])
            .filter((file) => file.type.startsWith('image/'));
        if (!files.length) {
            return;
        }
        // Some apps put both the image and its file name on the clipboard: keep only the image.
        event.preventDefault();
        // Pasted screenshots are all called image.png: give each its own name in the mail.
        addImages(files.map((file, index) => new File(
            [file], file.name === 'image.png' ? `image-${Date.now()}-${index}.png` : file.name,
            {type: file.type})));
    });

    form.addEventListener('dragover', (event) => event.preventDefault());
    form.addEventListener('drop', (event) => {
        const files = Array.from(event.dataTransfer?.files || []);
        if (!files.length) {
            return;
        }
        event.preventDefault();
        addImages(files);
    });

    form.querySelector('.messaging-attach').addEventListener('click', () => fileInput.click());
    fileInput.addEventListener('change', () => {
        addImages(Array.from(fileInput.files));
        fileInput.value = '';
    });

    form.addEventListener('submit', (event) => {
        if (!textarea.value.trim() && !images.length) {
            event.preventDefault();
            textarea.focus();
            return;
        }
        const transfer = new DataTransfer();
        images.forEach((file) => transfer.items.add(file));
        fileInput.files = transfer.files;
    });
});
