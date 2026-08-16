const progressBar = document.querySelector('#progressBar');
const menuButton = document.querySelector('#menuButton');
const navLinks = document.querySelector('#navLinks');

function updateProgress() {
  const height = document.documentElement.scrollHeight - window.innerHeight;
  progressBar.style.width = `${height > 0 ? (window.scrollY / height) * 100 : 0}%`;
}

window.addEventListener('scroll', updateProgress, { passive: true });
updateProgress();

menuButton.addEventListener('click', () => {
  const isOpen = navLinks.classList.toggle('open');
  menuButton.setAttribute('aria-expanded', String(isOpen));
});

navLinks.addEventListener('click', (event) => {
  if (event.target.closest('a')) {
    navLinks.classList.remove('open');
    menuButton.setAttribute('aria-expanded', 'false');
  }
});

document.querySelectorAll('[data-copy-target]').forEach((button) => {
  button.addEventListener('click', async () => {
    const target = document.getElementById(button.dataset.copyTarget);
    try {
      await navigator.clipboard.writeText(target.innerText);
      const label = button.textContent;
      button.textContent = 'Copied';
      setTimeout(() => { button.textContent = label; }, 1400);
    } catch {
      button.textContent = 'Select & copy';
    }
  });
});
