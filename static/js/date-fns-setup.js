// Load full date-fns library from CDN
const dateFnsScript = document.createElement('script');
dateFnsScript.src = 'https://cdn.jsdelivr.net/npm/date-fns@2.29.3/date-fns.min.js';
dateFnsScript.onload = function() {
    console.log('date-fns loaded successfully');
    window.dateFns = {
        formatRelative: window.dateFns.formatRelative
    };
};
document.head.appendChild(dateFnsScript);
