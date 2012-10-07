SET @OLD_UNIQUE_CHECKS=@@UNIQUE_CHECKS, UNIQUE_CHECKS=0;
SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0;
SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='TRADITIONAL,ALLOW_INVALID_DATES';

CREATE SCHEMA IF NOT EXISTS `txircd` DEFAULT CHARACTER SET utf8 ;
USE `txircd` ;

-- -----------------------------------------------------
-- Table `txircd`.`donors`
-- -----------------------------------------------------
DROP TABLE IF EXISTS `txircd`.`donors` ;

CREATE  TABLE IF NOT EXISTS `txircd`.`donors` (
  `id` INT(10) UNSIGNED NOT NULL AUTO_INCREMENT ,
  `email` VARCHAR(255) NOT NULL ,
  `password` VARCHAR(255) NULL DEFAULT NULL ,
  `display_name` VARCHAR(255) NULL DEFAULT NULL ,
  PRIMARY KEY (`id`) ,
  UNIQUE INDEX `email_UNIQUE` (`email` ASC) )
ENGINE = MyISAM
DEFAULT CHARACTER SET = utf8
COMMENT = 'Donor accounts';


-- -----------------------------------------------------
-- Table `txircd`.`irc_nicks`
-- -----------------------------------------------------
DROP TABLE IF EXISTS `txircd`.`irc_nicks` ;

CREATE  TABLE IF NOT EXISTS `txircd`.`irc_nicks` (
  `id` INT(10) UNSIGNED NOT NULL AUTO_INCREMENT ,
  `donor_id` INT(10) UNSIGNED NULL DEFAULT NULL ,
  `nick` VARCHAR(255) NOT NULL ,
  PRIMARY KEY (`id`) )
ENGINE = MyISAM
DEFAULT CHARACTER SET = utf8
COMMENT = 'IRC Nicks';


-- -----------------------------------------------------
-- Table `txircd`.`irc_tokens`
-- -----------------------------------------------------
DROP TABLE IF EXISTS `txircd`.`irc_tokens` ;

CREATE  TABLE IF NOT EXISTS `txircd`.`irc_tokens` (
  `id` INT(10) UNSIGNED NOT NULL AUTO_INCREMENT ,
  `donor_id` INT(10) UNSIGNED NULL DEFAULT NULL ,
  `token` VARCHAR(255) NOT NULL ,
  PRIMARY KEY (`id`) )
ENGINE = MyISAM
DEFAULT CHARACTER SET = utf8
COMMENT = 'IRC Tokens';



SET SQL_MODE=@OLD_SQL_MODE;
SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS;
SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS;
