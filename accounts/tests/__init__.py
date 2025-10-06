"""Tests for accounts app."""

# Import all test classes to ensure pytest can discover them

# Model tests
# Admin tests
from .test_admin import UserAdminRegistrationTests

# Form tests
from .test_forms import (
    ChangeEmailFormTests,
    CustomPasswordChangeFormTests,
    EducationFormTests,
    PasswordResetConfirmFormTests,
    PasswordResetRequestFormTests,
    ProfileFormTests,
    SignUpFormTests,
    WorkExperienceFormTests,
)

# Integration tests
from .test_integration import (
    EmailChangeFlowTests,
    PasswordChangeFlowTests,
    PasswordResetFlowTests,
    ProfileManagementFlowTests,
    UserRegistrationFlowTests,
)
from .test_models import (
    EducationModelTests,
    UserModelTests,
    UserProfileModelTests,
    WorkExperienceModelTests,
)

# Task tests
from .test_tasks import PasswordResetTaskTests

# View tests
from .test_views import (
    AccountsIndexViewTests,
    ChangeEmailViewTests,
    ChangePasswordViewTests,
    DisconnectSocialAccountViewTests,
    LogoutViewTests,
    PasswordResetConfirmViewTests,
    PasswordResetDoneViewTests,
    PasswordResetRequestViewTests,
    ProfileEditViewTests,
    ProfileViewTests,
    RedeemConfirmViewTests,
    RedemptionListViewTests,
    ShopListViewTests,
    SignInViewTests,
    SignUpViewTests,
    SocialConnectionsViewTests,
)

__all__ = [
    # View tests
    "AccountsIndexViewTests",
    # Form tests
    "ChangeEmailFormTests",
    "ChangeEmailViewTests",
    "ChangePasswordViewTests",
    "CustomPasswordChangeFormTests",
    "DisconnectSocialAccountViewTests",
    "EducationFormTests",
    # Model tests
    "EducationModelTests",
    # Integration tests
    "EmailChangeFlowTests",
    "LogoutViewTests",
    "PasswordChangeFlowTests",
    "PasswordResetConfirmFormTests",
    "PasswordResetConfirmViewTests",
    "PasswordResetDoneViewTests",
    "PasswordResetFlowTests",
    "PasswordResetRequestFormTests",
    "PasswordResetRequestViewTests",
    # Task tests
    "PasswordResetTaskTests",
    "ProfileEditViewTests",
    "ProfileFormTests",
    "ProfileManagementFlowTests",
    "ProfileViewTests",
    "RedeemConfirmViewTests",
    "RedemptionListViewTests",
    "ShopListViewTests",
    "SignInViewTests",
    "SignUpFormTests",
    "SignUpViewTests",
    "SocialConnectionsViewTests",
    # Admin tests
    "UserAdminRegistrationTests",
    "UserModelTests",
    "UserProfileModelTests",
    "UserRegistrationFlowTests",
    "WorkExperienceFormTests",
    "WorkExperienceModelTests",
]
