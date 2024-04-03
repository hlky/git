import json
import logging
import pathlib
from typing import cast, Optional

import click

import requests
import tqdm

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

products_url = "https://www.gucci.com/{lang_code}/c/productgrid?categoryCode={category_code}&show=All&page={page}"
product_media_url = "https://prod-catalog-api.guccidigital.io/v1/media/{product_code}"
product_details_url = (
    "https://prod-catalog-api.guccidigital.io/v1/products/{product_code}"
)

default_categories = [
    "women",
    "men",
    "jewelry-watches",
]

lang_code = ["us/en"]
language = "en"

user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 Edg/122.0.0.0"
headers = {
    "User-Agent": user_agent,
}

image_style = "DarkGray_Center_0_0_2400x2400"


def get(url: str) -> None | dict | list:
    response = requests.get(
        url,
        headers=headers,
    )
    if not response.ok:
        logger.debug(f"Failed to get {url}")
        return None
    try:
        data = response.json()
        if isinstance(data, dict):
            return cast(dict, data)
        elif isinstance(data, list):
            return cast(list, data)
        else:
            logger.debug(f"Failed to parse JSON from {url}")
            return None
    except json.JSONDecodeError:
        logger.debug(f"Failed to parse JSON from {url}")
        return None


def download(url: str, path: pathlib.Path) -> None:
    if path.exists():
        logger.debug(f"File {path} already exists")
        return
    response = requests.get(
        url,
        headers=headers,
        stream=True,
    )
    if not response.ok:
        logger.debug(f"Failed to download {url}")
        return
    with open(path, "wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)
    logger.debug(f"Downloaded {url} to {path}")


class Gucci:
    def __init__(
        self,
        gucci_path: str = "gucci.json",
        categories: list[str] = default_categories,
        lang_code: list[str] = lang_code,
        language: str = language,
        product_details: bool = False,
    ):
        self.categories = categories
        self.gucci_path = pathlib.Path(gucci_path)
        self.gucci_root = self.gucci_path.resolve().parent
        logger.info(f"Gucci root: {self.gucci_root}, Gucci path: {self.gucci_path}")
        self.lang_code = lang_code
        self.language = language
        self.products = {}
        if self.gucci_path.exists():
            with open(gucci_path, "r", encoding="utf-8") as f:
                self.products = cast(dict[str, dict], json.load(f))
                logger.info(f"Loaded {len(self.products)} products from {gucci_path}")
        self.product_details = product_details
        self.initial_count = len(self.products)

    def download_images(
        self, products: Optional[dict[str, dict]] = None
    ) -> dict[str, dict]:
        if products is None:
            products = self.products
        pbar = tqdm.tqdm(total=len(products))
        for _, product in products.items():
            product_code = cast(str, product["productCode"])
            pbar.set_description(product_code)
            product_dir = self.gucci_root / product_code
            product_dir.mkdir(parents=True, exist_ok=True)
            images = cast(list[str], product["images"])
            number_of_images = len(images)
            if (
                product_dir.exists()
                and len(list(product_dir.glob("*.jpg"))) == number_of_images
            ):
                pbar.update(1)
                logger.debug(f"Images already downloaded for {product_code}")
                continue
            pbar.set_postfix(images=number_of_images)
            for idx, image in enumerate(images):
                filename = image.split("/")[-1]
                image_path = product_dir / filename
                download(image, image_path)
                pbar.set_postfix(current=idx + 1, images=number_of_images)
            pbar.update(1)
        return products

    def get_media(self, product_code: str) -> list[str]:
        data = get(product_media_url.format(product_code=product_code))
        if data is None:
            logger.debug(f"Failed to get media for {product_code}")
            return []
        data = cast(list[dict[str, str]], data)
        data = [image["url"].replace("$format$", image_style) for image in data]
        return data

    def get_product_details(self, product_code: str) -> dict[str, list | str]:
        data = get(product_details_url.format(product_code=product_code))
        if data is None:
            logger.debug(f"Failed to get product details for {product_code}")
            return {}
        data = cast(dict[str, list | str], data)
        drop_keys = [
            "assortments",
            "availability",
            "categories",
            "status",
            "variants",
            "project",
            "prices",
            "lastUpdated",
            "exotic",
            "genders",
            "materialCare",
            "styleCode",
            "language",
            "madeIn",
            "translations",
        ]
        rename = {
            "editorialDescription": "editorial",
            "variationDescription": "variation",
            "departmentDescription": "department",
            "subDepartmentDescription": "subDepartment",
            "seasonDescription": "season",
            "detailParts": "details",
        }
        translations = cast(list[dict[str, str]], data.get("translations", []))
        for translation in translations:
            language = translation.get("language", "")
            if language == self.language:
                data.update(translation)
        data = {rename.get(k, k): v for k, v in data.items() if k not in drop_keys}
        for key in rename:
            data.pop(key, None)
        logger.debug(f"Product details for {product_code}: {data}")
        return data

    def get_products(self, category_code: str, lang_code: str):
        if category_code not in self.categories:
            logger.debug(f"Category {category_code} not in {self.categories}")
            return

        def process_url(url: str) -> str:
            style = url.split("/")[4]
            logger.debug(f"Style: {style}")
            return "https:" + url.replace(style, image_style)

        def deduplicate_images(images: list[str]) -> list[str]:
            filenames: set[str] = set()
            result: set[str] = set()
            for image in images:
                filename = image.split("/")[-1]
                logger.debug(f"Filename: {filename}")
                if "-" in filename:
                    filename = filename.split("-")[0] + ".jpg"
                    logger.debug(f"New filename: {filename}")
                if filename in filenames:
                    logger.debug(f"Duplicate image {filename}")
                    continue
                filenames.add(filename)
                result.add(image)
            return list(result)

        def process_images(product: dict) -> list[str]:
            primary_image = cast(dict[str, str], product["primaryImage"])
            alternate_gallery_images = cast(
                list[dict[str, str]], product["alternateGalleryImages"]
            )
            alternate_image = cast(dict[str, str], product["alternateImage"])
            images = [image["src"] for image in alternate_gallery_images]
            images.append(primary_image["src"])
            images.append(alternate_image["src"])
            images = deduplicate_images([process_url(image) for image in images])
            return images

        drop_keys = [
            "showOutOfStockLabel",
            "showAvailableInStoreOnlyLabel",
            "videoBackgroundImage",
            "zoomImagePrimary",
            "zoomImageAlternate",
            "filterType",
            "nonTransactionalWebSite",
            "isDiyProduct",
            "inStockEntry",
            "inStoreStockEntry",
            "inStoreStockRegionalEntry",
            "visibleWithoutStock",
            "showSavedItemIcon",
            "type",
            "saleType",
            "fullPrice",
            "position",
            "isFavorite",
            "isOnlineExclusive",
            "isRegionalOnlineExclusive",
            "regionalOnlineExclusiveMsg",
            "isExclusiveSale",
            "label",
            "imgBase",
            "productName",
            "primaryImage",
            "alternateImage",
            "alternateGalleryImages",
        ]
        page = 0
        number_of_pages = 1
        while page < number_of_pages:
            data = get(
                products_url.format(
                    lang_code=lang_code, category_code=category_code, page=page
                )
            )
            if data is None:
                logger.debug(
                    f"Failed to get products for {category_code} on page {page}"
                )
                break
            data = cast(dict[str, dict[str, list[dict]] | int | str], data)
            number_of_pages = cast(int, data["numberOfPages"])
            products = cast(dict[str, list[dict[str, list | str]]], data["products"])
            count = len(products["items"])
            if count == 0:
                logger.debug(f"No products found for {category_code} on page {page}")
                break
            logger.debug(f"Found {count} products for {category_code} on page {page}")
            pbar = tqdm.tqdm(total=count)
            pbar.set_postfix(page=page, category=category_code)
            for _, product in enumerate(products["items"]):
                product_code = cast(str, product["productCode"])
                if product_code in self.products:
                    logger.debug(f"Product {product_code} already processed")
                    pbar.update(1)
                    continue
                else:
                    pbar.set_description(f"New product {product_code}")
                logger.debug(f"Processing product {product_code}")
                product["images"] = process_images(product)
                for key in drop_keys:
                    product.pop(key, None)
                if self.product_details:
                    product.update(self.get_product_details(product_code))
                self.products[product_code] = product
                pbar.update(1)
            page += 1

    def save(self, gucci_path: Optional[str] = None):
        if gucci_path is None:
            gucci_path = str(self.gucci_path)
        with open(gucci_path, "w", encoding="utf-8") as f:
            json.dump(self.products, f, ensure_ascii=False, indent=2)
        logger.info(f"Saved {len(self.products)} products to {gucci_path}")
        logger.info(f"Added {len(self.products) - self.initial_count} new products")

    def run(
        self,
        save_path: Optional[str] = None,
    ):
        for lang_code in self.lang_code:
            logger.info(f"Processing language {lang_code}")
            for category in self.categories:
                logger.info(f"Processing category {category}")
                self.get_products(category, lang_code)
        self.save(gucci_path=save_path)


@click.command()
@click.option(
    "--gucci-path", default="gucci.json", help="Path to Gucci JSON file", type=str
)
@click.option(
    "--categories",
    default=default_categories,
    help="Categories to process",
    multiple=True,
    type=str,
)
@click.option(
    "--lang-code",
    "-l",
    default=lang_code,
    help="Language code",
    type=str,
    multiple=True,
)
@click.option("--language", default=language, help="Language", type=str)
@click.option(
    "--product-details", is_flag=True, help="Get product details", default=False
)
@click.option("--save-path", help="Save path", default=None, type=str)
@click.option("--download-images", is_flag=True, help="Download images", default=False)
def run(
    gucci_path: str = "gucci.json",
    categories: list[str] = default_categories,
    lang_code: list[str] = lang_code,
    language: str = language,
    product_details: bool = False,
    save_path: Optional[str] = None,
    download_images: bool = False,
):
    gucci = Gucci(
        gucci_path=gucci_path,
        categories=categories,
        lang_code=lang_code,
        language=language,
        product_details=product_details,
    )
    if download_images:
        gucci.download_images()
    else:
        gucci.run(save_path=save_path)


if __name__ == "__main__":
    run()
