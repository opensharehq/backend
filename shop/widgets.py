"""Image crop widget using Cropper.js for Django Admin."""

from django.forms.widgets import ClearableFileInput
from django.utils.safestring import mark_safe


class ImageCropWidget(ClearableFileInput):
    """A widget that allows image cropping with a fixed aspect ratio using Cropper.js."""

    class Media:
        """Widget media assets."""

        css = {
            "all": (
                "https://cdnjs.cloudflare.com/ajax/libs/cropperjs/1.6.2/cropper.min.css",
            )
        }
        js = ("https://cdnjs.cloudflare.com/ajax/libs/cropperjs/1.6.2/cropper.min.js",)

    def __init__(self, aspect_ratio=1, crop_width=800, crop_height=400, attrs=None):
        """Initialize with crop dimensions and aspect ratio."""
        self.aspect_ratio = aspect_ratio
        self.crop_width = crop_width
        self.crop_height = crop_height
        super().__init__(attrs=attrs)

    def render(self, name, value, attrs=None, renderer=None):
        """Render the image crop widget HTML with Cropper.js integration."""
        # Get the base widget HTML (file input + clear checkbox)
        base_html = super().render(name, value, attrs, renderer)

        widget_id = attrs.get("id", name) if attrs else name
        crop_data_input_name = f"{name}_crop_data"
        crop_data_input_id = f"{widget_id}_crop_data"

        # Current image preview
        current_preview = ""
        if value and hasattr(value, "url"):
            current_preview = f"""
            <div id="{widget_id}_current_preview" style="margin-bottom: 10px;">
                <p style="font-weight: bold; margin-bottom: 5px;">当前图片:</p>
                <img src="{value.url}" style="max-width: 300px; max-height: 150px;
                     border: 1px solid #ddd; border-radius: 4px;" />
            </div>
            """

        html = f"""
        <div class="image-crop-widget" id="{widget_id}_wrapper"
             style="margin-bottom: 15px;">
            {current_preview}

            <div style="margin-bottom: 10px;">
                {base_html}
            </div>

            <!-- Cropper area -->
            <div id="{widget_id}_crop_area" style="display: none;
                 margin-top: 10px; border: 1px solid #ccc; padding: 10px;
                 border-radius: 4px; background: #f9f9f9;">
                <p style="font-weight: bold; margin-bottom: 8px;">
                    裁剪预览 (宽高比 {self.aspect_ratio:.2f}):
                </p>
                <div style="max-width: 600px; max-height: 400px; overflow: hidden;">
                    <img id="{widget_id}_crop_image" style="max-width: 100%;
                         display: block;" />
                </div>
                <button type="button" id="{widget_id}_crop_btn"
                        style="margin-top: 10px; padding: 6px 16px;
                        background: #417690; color: #fff; border: none;
                        border-radius: 4px; cursor: pointer; font-size: 13px;">
                    确认裁剪
                </button>
                <button type="button" id="{widget_id}_cancel_btn"
                        style="margin-top: 10px; margin-left: 8px; padding: 6px 16px;
                        background: #999; color: #fff; border: none;
                        border-radius: 4px; cursor: pointer; font-size: 13px;">
                    取消
                </button>
            </div>

            <!-- Crop result preview -->
            <div id="{widget_id}_result_area" style="display: none; margin-top: 10px;">
                <p style="font-weight: bold; margin-bottom: 5px; color: green;">
                    ✓ 已裁剪:
                </p>
                <img id="{widget_id}_result_image" style="max-width: 300px;
                     max-height: 150px; border: 1px solid #ddd;
                     border-radius: 4px;" />
            </div>

            <!-- Hidden input for base64 crop data -->
            <input type="hidden" name="{crop_data_input_name}"
                   id="{crop_data_input_id}" value="" />
        </div>

        <script>
        (function() {{
            var aspectRatio = {self.aspect_ratio};
            var cropWidth = {self.crop_width};
            var cropHeight = {self.crop_height};
            var widgetId = "{widget_id}";
            var cropper = null;

            function initWidget() {{
                var fileInput = document.getElementById(widgetId);
                if (!fileInput) return;

                fileInput.addEventListener("change", function(e) {{
                    var file = e.target.files[0];
                    if (!file || !file.type.startsWith("image/")) return;

                    var reader = new FileReader();
                    reader.onload = function(ev) {{
                        var cropArea = document.getElementById(
                            widgetId + "_crop_area");
                        var cropImage = document.getElementById(
                            widgetId + "_crop_image");
                        var resultArea = document.getElementById(
                            widgetId + "_result_area");

                        cropImage.src = ev.target.result;
                        cropArea.style.display = "block";
                        resultArea.style.display = "none";

                        // Destroy previous cropper instance
                        if (cropper) {{
                            cropper.destroy();
                            cropper = null;
                        }}

                        // Wait for image to load before initializing cropper
                        cropImage.onload = function() {{
                            cropper = new Cropper(cropImage, {{
                                aspectRatio: aspectRatio,
                                viewMode: 1,
                                autoCropArea: 1,
                                responsive: true,
                                restore: false,
                                guides: true,
                                center: true,
                                highlight: true,
                                cropBoxMovable: true,
                                cropBoxResizable: true,
                                toggleDragModeOnDblclick: false,
                            }});
                        }};
                    }};
                    reader.readAsDataURL(file);
                }});

                // Confirm crop button
                var cropBtn = document.getElementById(widgetId + "_crop_btn");
                cropBtn.addEventListener("click", function() {{
                    if (!cropper) return;

                    var canvas = cropper.getCroppedCanvas({{
                        width: cropWidth,
                        height: cropHeight,
                        imageSmoothingEnabled: true,
                        imageSmoothingQuality: "high",
                    }});

                    var dataUrl = canvas.toDataURL("image/jpeg", 0.9);
                    var hiddenInput = document.getElementById(
                        widgetId + "_crop_data");
                    hiddenInput.value = dataUrl;

                    // Show result preview
                    var resultArea = document.getElementById(
                        widgetId + "_result_area");
                    var resultImage = document.getElementById(
                        widgetId + "_result_image");
                    resultImage.src = dataUrl;
                    resultArea.style.display = "block";

                    // Hide crop area
                    var cropArea = document.getElementById(
                        widgetId + "_crop_area");
                    cropArea.style.display = "none";

                    // Destroy cropper
                    cropper.destroy();
                    cropper = null;
                }});

                // Cancel button
                var cancelBtn = document.getElementById(widgetId + "_cancel_btn");
                cancelBtn.addEventListener("click", function() {{
                    var cropArea = document.getElementById(
                        widgetId + "_crop_area");
                    cropArea.style.display = "none";

                    if (cropper) {{
                        cropper.destroy();
                        cropper = null;
                    }}

                    // Clear file input
                    fileInput.value = "";
                }});
            }}

            // Init when DOM is ready
            if (document.readyState === "loading") {{
                document.addEventListener("DOMContentLoaded", initWidget);
            }} else {{
                initWidget();
            }}
        }})();
        </script>
        """
        return mark_safe(html)  # noqa: S308
