const toggle = document.getElementById('menu-toggle');
const nav = document.getElementById('navlinks');
if (toggle && nav) {
  toggle.addEventListener('click', () => {
    const open = nav.classList.toggle('open');
    toggle.setAttribute('aria-expanded', String(open));
  });
}
const observer = new IntersectionObserver((entries) => {
  entries.forEach(entry => {
    if (entry.isIntersecting) {
      entry.target.classList.add('visible');
      observer.unobserve(entry.target);
    }
  });
}, {threshold: 0.08});
document.querySelectorAll('.feature,.listing,.stat,.section-heading').forEach(el => {
  el.classList.add('reveal');
  observer.observe(el);
});
