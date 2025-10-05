// npm package: tinymce
// github link: https://github.com/tinymce/tinymce

'use strict';

(function () {
  const tinymceExample = document.querySelector('#tinymceExample');
  const bodyColor = getComputedStyle(document.documentElement).getPropertyValue('--bs-body-color').trim();

  if (tinymceExample) {
    const options = {
      selector: '#tinymceExample',
      min_height: 350,
      plugins: [
        'advlist', 'autoresize', 'autolink', 'lists', 'link', 'image', 'charmap', 'preview', 'anchor', 'pagebreak',
        'searchreplace', 'wordcount', 'visualblocks', 'visualchars', 'code', 'fullscreen',
      ],
      toolbar: 'undo redo | insert | styleselect | bold italic | alignleft aligncenter alignright alignjustify | bullist numlist outdent indent | link image | print preview media | forecolor backcolor emoticons | codesample help',
      image_advtab: true,
      promotion: false,
      license_key: 'gpl',
      content_style: `body { color: ${bodyColor}; }`,

    };

    const theme = localStorage.getItem('theme');
    if (theme === 'dark') {
      options.content_css = 'dark';
      const bgColor = getComputedStyle(document.documentElement).getPropertyValue('--bs-body-bg');
      options.content_style += ` body { background: ${bgColor}; }`;
    } else if (theme === 'light') {
      options.content_css = 'default';
    }

    tinymce.init(options);
  }
})();