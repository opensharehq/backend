'use strict';

function showSwal(type) {
  if (type === 'basic') {
    Swal.fire({
      text: 'Any fool can use a computer',
      confirmButtonText: 'Close',
      customClass: {
        confirmButton: 'btn btn-danger'
      },
      buttonsStyling: false
    });
  } else if (type === 'title-and-text') {
    Swal.fire({
      title: 'The Internet?',
      text: 'That thing is still around?',
      icon: 'question',
      confirmButtonText: 'OK',
      customClass: {
        confirmButton: 'btn btn-primary'
      },
      buttonsStyling: false
    });
  } else if (type === 'title-icon-text-footer') {
    Swal.fire({
      icon: 'error',
      title: 'Oops...',
      text: 'Something went wrong!',
      footer: '<a href="#">Why do I have this issue?</a>',
      confirmButtonText: 'Close',
      customClass: {
        confirmButton: 'btn btn-warning'
      },
      buttonsStyling: false
    });
  } else if (type === 'custom-html') {
    Swal.fire({
      title: '<strong>HTML <u>example</u></strong>',
      icon: 'info',
      html:
        'You can use <b>bold text</b>, ' +
        '<a href="//github.com">links</a> ' +
        'and other HTML tags',
      showCloseButton: true,
      showCancelButton: true,
      focusConfirm: false,
      confirmButtonText:
        '<i data-lucide="thumbs-up" class="icon-md"></i> Great!',
      confirmButtonAriaLabel: 'Thumbs up, great!',
      cancelButtonText:
        '<i data-lucide="thumbs-down" class="icon-md"></i>',
      cancelButtonAriaLabel: 'Thumbs down',
      customClass: {
        confirmButton: 'btn btn-success me-2',
        cancelButton: 'btn btn-secondary'
      },
      buttonsStyling: false
    });
    if (window.lucide) lucide.createIcons(); // ensure lucide is loaded
  } else if (type === 'custom-position') {
    Swal.fire({
      position: 'top-end',
      icon: 'success',
      title: 'Your work has been saved',
      showConfirmButton: false,
      timer: 1500
    });
  } else if (type === 'passing-parameter-execute-cancel') {
    const swalWithBootstrapButtons = Swal.mixin({
      customClass: {
        cancelButton: 'btn btn-danger me-2',
        confirmButton: 'btn btn-success',
      },
      buttonsStyling: false
    });

    swalWithBootstrapButtons.fire({
      title: 'Are you sure?',
      text: "You won't be able to revert this!",
      icon: 'warning',
      showCancelButton: true,
      confirmButtonText: 'Yes, delete it!',
      cancelButtonText: 'No, cancel!',
      reverseButtons: true
    }).then((result) => {
      if (result.isConfirmed) {
        swalWithBootstrapButtons.fire(
          'Deleted!',
          'Your file has been deleted.',
          'success'
        );
      } else if (result.dismiss === Swal.DismissReason.cancel) {
        swalWithBootstrapButtons.fire(
          'Cancelled',
          'Your imaginary file is safe :)',
          'error'
        );
      }
    });
  } else if (type === 'message-with-auto-close') {
    let timerInterval;
    Swal.fire({
      title: 'Auto close alert!',
      html: 'I will close in <b></b> milliseconds.',
      timer: 2000,
      timerProgressBar: true,
      didOpen: () => {
        Swal.showLoading();
        timerInterval = setInterval(() => {
          const content = Swal.getHtmlContainer();
          if (content) {
            const b = content.querySelector('b');
            if (b) {
              b.textContent = Swal.getTimerLeft();
            }
          }
        }, 100);
      },
      willClose: () => {
        clearInterval(timerInterval);
      }
    }).then((result) => {
      if (result.dismiss === Swal.DismissReason.timer) {
        console.log('I was closed by the timer');
      }
    });
  } else if (type === 'message-with-custom-image') {
    Swal.fire({
      title: 'Sweet!',
      text: 'Modal with a custom image.',
      // imageUrl: 'https://unsplash.it/400/200',
      imageUrl: '../../../assets/images/others/placeholder.jpg',
      imageWidth: 400,
      imageHeight: 200,
      imageAlt: 'Custom image',
      confirmButtonText: 'OK',
      customClass: {
        confirmButton: 'btn btn-info'
      },
      buttonsStyling: false
    });
  } else if (type === 'mixin') {
    const Toast = Swal.mixin({
      toast: true,
      position: 'top-end',
      showConfirmButton: false,
      timer: 3000,
      timerProgressBar: true
    });

    Toast.fire({
      icon: 'success',
      title: 'Signed in successfully'
    });
  }
}
