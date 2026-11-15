document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.flash').forEach((flash) => {
    setTimeout(() => {
      flash.style.opacity = '0';
      flash.style.transform = 'translateY(-6px)';
      flash.style.transition = 'all 0.2s ease';
      setTimeout(() => flash.remove(), 220);
    }, 3500);
  });
});
