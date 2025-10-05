// npm package: bootstrap-maxlength
// github link: https://github.com/mimo84/bootstrap-maxlength

'use strict';

(function () {

  if ($('#defaultconfig').length) {
    $('#defaultconfig').maxlength({
      warningClass: "badge mt-1 bg-success",
      limitReachedClass: "badge mt-1 bg-danger"
    });
  }

  if ($('#defaultconfig-2').length) {
    $('#defaultconfig-2').maxlength({
      alwaysShow: true,
      threshold: 20,
      warningClass: "badge mt-1 bg-success",
      limitReachedClass: "badge mt-1 bg-danger"
    });
  }

  if ($('#defaultconfig-3').length) {
    $('#defaultconfig-3').maxlength({
      alwaysShow: true,
      threshold: 10,
      warningClass: "badge mt-1 bg-success",
      limitReachedClass: "badge mt-1 bg-danger",
      separator: ' of ',
      preText: 'You have ',
      postText: ' chars remaining.',
      validate: true
    });
  }

  if ($('#maxlength-textarea').length) {
    $('#maxlength-textarea').maxlength({
      alwaysShow: true,
      warningClass: "badge mt-1 bg-success",
      limitReachedClass: "badge mt-1 bg-danger"
    });
  }

})();