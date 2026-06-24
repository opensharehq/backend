"""Admin forms for shop application."""

import base64
import binascii
import uuid

from django import forms
from django.core.files.base import ContentFile

from .models import ShopItem
from .widgets import ImageCropWidget


class ShopItemAdminForm(forms.ModelForm):
    """Admin form for ShopItem with image cropping support."""

    class Meta:
        """Form metadata."""

        model = ShopItem
        fields = [
            "name_zh",
            "name_en",
            "brief_zh",
            "brief_en",
            "description_zh",
            "description_en",
            "image_card",
            "image_detail",
            "cost",
            "stock",
            "is_active",
            "requires_shipping",
            "allowed_tags",
            "message_title_template_zh",
            "message_title_template_en",
            "message_content_template_zh",
            "message_content_template_en",
            "coupon_type",
        ]
        widgets = {
            "image_card": ImageCropWidget(
                aspect_ratio=2, crop_width=800, crop_height=400
            ),
            "image_detail": ImageCropWidget(
                aspect_ratio=1, crop_width=1000, crop_height=1000
            ),
        }

    def _process_crop_data(self, field_name):
        """Process base64 crop data for a given field and return a ContentFile or None."""
        crop_data_key = f"{field_name}_crop_data"
        crop_data = self.data.get(crop_data_key, "")

        if crop_data and crop_data.startswith("data:image/"):
            # Parse data URL: data:image/jpeg;base64,/9j/4AAQ...
            try:
                header, encoded = crop_data.split(",", 1)
                # Extract mime type to determine extension
                mime_type = header.split(":")[1].split(";")[0]
                ext_map = {
                    "image/jpeg": "jpg",
                    "image/png": "png",
                    "image/webp": "webp",
                }
                ext = ext_map.get(mime_type, "jpg")

                # Decode base64
                file_data = base64.b64decode(encoded)
                filename = f"{uuid.uuid4().hex}.{ext}"
                return ContentFile(file_data, name=filename)
            except (ValueError, IndexError, binascii.Error):
                pass
        return None

    def save(self, commit=True):
        """Save form with base64 crop data processing."""
        instance = super().save(commit=False)

        # Process image_card crop data
        card_file = self._process_crop_data("image_card")
        if card_file:
            # Delete old file if exists
            if instance.image_card:
                instance.image_card.delete(save=False)
            instance.image_card.save(card_file.name, card_file, save=False)

        # Process image_detail crop data
        detail_file = self._process_crop_data("image_detail")
        if detail_file:
            # Delete old file if exists
            if instance.image_detail:
                instance.image_detail.delete(save=False)
            instance.image_detail.save(detail_file.name, detail_file, save=False)

        if commit:
            instance.save()
            self.save_m2m()

        return instance
